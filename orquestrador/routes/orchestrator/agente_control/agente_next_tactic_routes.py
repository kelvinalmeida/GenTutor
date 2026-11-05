import json
import requests
import logging
from flask import Blueprint, jsonify, request
from ...services_routs import CONTROL_URL, STRATEGIES_URL, USER_URL

logging.basicConfig(level=logging.INFO)

agente_next_tactic_bp = Blueprint('agente_next_tactic_bp', __name__)


@agente_next_tactic_bp.route('/orchestrator/agent/adaptive_next_tactic', methods=['POST'])
def adaptive_next_tactic():
    """
    Escolhe a próxima tática do aluno.

    - Se o aluno tem um plano armazenado (criado por plan_session), usa-o diretamente
      sem chamar a IA — transição rápida e consistente com o planejamento multi-passo.
    - Se não há plano (modo legado), agrega contexto completo e chama a IA.

    Nunca repete táticas; quando todas são concluídas, encerra a sessão do aluno.
    """
    data = request.get_json() or {}
    student_id = data.get('student_id')
    session_id = data.get('session_id')
    is_first = bool(data.get('is_first', False))
    completed_tactic_index = data.get('completed_tactic_index')

    if student_id is None or session_id is None:
        return jsonify({"error": "student_id e session_id são obrigatórios"}), 400

    try:
        # 1. Dados da sessão
        session_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
        if session_resp.status_code != 200:
            return jsonify({"error": "Falha ao buscar sessão"}), 502
        session_data = session_resp.json()

        strategy_ids = session_data.get('strategies', [])
        student_ids = session_data.get('students', [])
        strategy_id = strategy_ids[0] if strategy_ids else None

        # 2. Progresso atual do aluno (índice + executados + plano)
        current_tactic_index = 0
        executed_tactic_indices = []
        session_plan = None
        try:
            progress_resp = requests.get(
                f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
                timeout=10
            )
            if progress_resp.status_code == 200:
                prog = progress_resp.json()
                current_tactic_index = prog.get('current_tactic_index', 0)
                executed_tactic_indices = list(prog.get('executed_tactic_indices', []))
                session_plan_raw = prog.get('session_plan')
                if session_plan_raw:
                    try:
                        session_plan = json.loads(session_plan_raw)
                    except Exception:
                        session_plan = None
        except Exception as e:
            logging.warning("Erro ao buscar tactic_index student_id=%s: %s", student_id, e)

        # Determina qual tática foi concluída
        if not is_first:
            tactic_just_done = (
                int(completed_tactic_index) if completed_tactic_index is not None
                else current_tactic_index
            )
            if tactic_just_done not in executed_tactic_indices:
                executed_tactic_indices.append(tactic_just_done)

        # 3. Táticas da estratégia
        strategy_tactics = []
        if strategy_id:
            try:
                strat_resp = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}", timeout=10)
                if strat_resp.status_code == 200:
                    strategy_tactics = strat_resp.json().get('tatics', [])
            except Exception as e:
                logging.warning("Erro ao buscar táticas strategy_id=%s: %s", strategy_id, e)

        if not strategy_tactics:
            return jsonify({"error": "Sem táticas na estratégia"}), 400

        # 4. Táticas restantes (não executadas)
        remaining_indices = [i for i in range(len(strategy_tactics)) if i not in executed_tactic_indices]

        if not remaining_indices:
            end_index = len(strategy_tactics)
            requests.post(
                f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/set_tactic",
                json={"tactic_index": end_index, "executed_tactic_indices": executed_tactic_indices},
                timeout=10
            )
            return jsonify({
                "next_tactic_index": end_index,
                "next_tactic_name": "Sessão Concluída",
                "reasoning": "Parabéns! Você completou todas as táticas desta sessão."
            }), 200

        # 5. Plano disponível: próxima tática em O(n) sem chamar a IA
        plan_seq = (session_plan or {}).get('tactic_sequence', [])
        if plan_seq:
            next_tactic_index = next(
                (i for i in plan_seq if i in remaining_indices),
                remaining_indices[0]
            )
            next_tactic_name = strategy_tactics[next_tactic_index].get('name', '') if next_tactic_index < len(strategy_tactics) else ''
            reasoning = (session_plan or {}).get('tactic_reasons', {}).get(str(next_tactic_index), 'Seguindo o plano personalizado.')
            logging.info("Plano armazenado: next=%s sequence=%s", next_tactic_index, plan_seq)
        else:
            # Modo legado: agrega contexto completo e chama IA
            next_tactic_index, next_tactic_name, reasoning = _decide_via_ai(
                student_id, session_id, session_data, student_ids, strategy_tactics,
                remaining_indices, executed_tactic_indices
            )

        # 6. Persiste a próxima tática
        set_resp = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/set_tactic",
            json={"tactic_index": next_tactic_index, "executed_tactic_indices": executed_tactic_indices},
            timeout=10
        )
        if set_resp.status_code != 200:
            return jsonify({"error": "Falha ao definir tática do aluno"}), 502

        return jsonify({
            "next_tactic_index": next_tactic_index,
            "next_tactic_name": next_tactic_name,
            "reasoning": reasoning
        }), 200

    except Exception as e:
        logging.error("Erro em adaptive_next_tactic: %s", str(e))
        return jsonify({"error": "Falha na orquestração"}), 500


def _decide_via_ai(student_id, session_id, session_data, student_ids, strategy_tactics, remaining_indices, executed_tactic_indices):
    """Agrega contexto completo e consulta a IA para decidir a próxima tática (modo sem plano)."""

    # Perfil individual do aluno
    student_profile = "Perfil não disponível."
    try:
        user_resp = requests.get(f"{USER_URL}/students/{student_id}/preferences", timeout=10)
        if user_resp.status_code == 200:
            d = user_resp.json()
            email_txt = "aceita e-mail" if d.get('pref_receive_email') else "não aceita e-mail"
            student_profile = (
                f"Nome: {d.get('name') or 'N/A'}. "
                f"Curso: {d.get('course') or 'N/A'}. "
                f"Idade: {d.get('age') or 'N/A'}. "
                f"Conteúdo preferido: {d.get('pref_content_type') or 'N/A'}. "
                f"Comunicação preferida: {d.get('pref_communication') or 'N/A'}. "
                f"{email_txt.capitalize()}."
            )
    except Exception as e:
        logging.warning("Erro ao buscar perfil student_id=%s: %s", student_id, e)

    # Perfil da turma
    class_profile = "Perfil da turma desconhecido."
    try:
        class_resp = requests.post(
            f"{USER_URL}/students/batch_preferences",
            json={"student_ids": student_ids},
            timeout=10
        )
        if class_resp.status_code == 200:
            students_raw = class_resp.json().get('students', [])
            if students_raw:
                lines = []
                for s in students_raw:
                    s_email = "aceita e-mail" if s.get('pref_receive_email') else "não aceita e-mail"
                    lines.append(
                        f"- {s.get('name') or 'Aluno'}: "
                        f"conteúdo '{s.get('pref_content_type') or 'N/A'}', "
                        f"comunicação '{s.get('pref_communication') or 'N/A'}', "
                        f"{s_email}."
                    )
                class_profile = "\n".join(lines)
    except Exception as e:
        logging.warning("Erro ao buscar perfil da turma: %s", e)

    # Notas do aluno
    exercise_scores = "Sem registros de exercícios."
    verified = [
        v for v in session_data.get('verified_answers', [])
        if str(v.get('student_id', '')) == str(student_id)
    ]
    if verified:
        scores = [v.get('score', 0) for v in verified]
        latest = verified[-1]
        total_q = max(len(latest.get('answers', [])), 1)
        latest_pct = int((latest.get('score', 0) / total_q) * 100)
        exercise_scores = (
            f"{len(scores)} tentativa(s). Notas: {scores}. "
            f"Última: {latest.get('score', 0)}/{total_q} ({latest_pct}%)."
        )

    # Username para filtrar mensagens do chat
    student_username = str(student_id)
    try:
        student_resp = requests.get(f"{USER_URL}/students/{student_id}", timeout=10)
        if student_resp.status_code == 200:
            student_username = student_resp.json().get('username', str(student_id))
    except Exception as e:
        logging.warning("Erro ao buscar username student_id=%s: %s", student_id, e)

    # Últimas 5 mensagens no chat
    student_chat_messages = []
    for tactic in strategy_tactics:
        chat_id = tactic.get('chat_id')
        if not chat_id:
            continue
        try:
            chat_resp = requests.get(f"{STRATEGIES_URL}/chat/{chat_id}/general_messages", timeout=10)
            if chat_resp.status_code == 200:
                resp_json = chat_resp.json()
                msgs = resp_json.get('messages', []) if isinstance(resp_json, dict) else resp_json
                for msg in (msgs or []):
                    if isinstance(msg, dict) and msg.get('username') == student_username:
                        student_chat_messages.append(msg.get('content', ''))
        except Exception as e:
            logging.warning("Erro ao buscar mensagens chat_id=%s: %s", chat_id, e)
    last_5_messages = student_chat_messages[-5:]

    # Histórico de sessões anteriores
    student_history = ""
    try:
        hist_resp = requests.get(
            f"{USER_URL}/students/{student_id}/learning_history",
            params={"limit": 3},
            timeout=10
        )
        if hist_resp.status_code == 200:
            history_entries = hist_resp.json().get('history', [])
            if history_entries:
                lines = [f"- Sessão {h['session_id']}: {h['summary']}" for h in history_entries]
                student_history = "\n".join(lines)
    except Exception as e:
        logging.warning("Erro ao buscar histórico student_id=%s: %s", student_id, e)

    remaining_tactics = [
        {"index": i, "name": strategy_tactics[i].get('name', ''), "description": strategy_tactics[i].get('description', '')}
        for i in remaining_indices
    ]

    ai_payload = {
        "student_profile": student_profile,
        "class_profile": class_profile,
        "exercise_scores": exercise_scores,
        "remaining_tactics": remaining_tactics,
        "executed_tactic_indices": executed_tactic_indices,
        "chat_messages": last_5_messages,
        "student_history": student_history,
    }

    logging.info("Sem plano — chamando IA (legado): student_id=%s", student_id)

    ai_resp = requests.post(
        f"{STRATEGIES_URL}/agent/decide_adaptive_tactic",
        json=ai_payload,
        timeout=60
    )

    if ai_resp.status_code != 200:
        next_tactic_index = remaining_indices[0]
        next_tactic_name = strategy_tactics[next_tactic_index].get('name', '')
        reasoning = "Seguindo a próxima tática disponível (IA indisponível)."
    else:
        ai_data = ai_resp.json()
        next_tactic_index = ai_data.get('next_tactic_index')
        next_tactic_name = ai_data.get('next_tactic_name', '')
        reasoning = ai_data.get('reasoning', '')

        try:
            next_tactic_index = int(next_tactic_index)
            if next_tactic_index not in remaining_indices:
                next_tactic_index = remaining_indices[0]
                next_tactic_name = strategy_tactics[next_tactic_index].get('name', '')
        except (ValueError, TypeError):
            next_tactic_index = remaining_indices[0]
            next_tactic_name = strategy_tactics[next_tactic_index].get('name', '')

    return next_tactic_index, next_tactic_name, reasoning
