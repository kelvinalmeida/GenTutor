import json
import logging
import os
import requests
from flask import Blueprint, jsonify, request
from openai import OpenAI
from ...services_routs import CONTROL_URL, STRATEGIES_URL, USER_URL

logging.basicConfig(level=logging.INFO)

agente_plan_bp = Blueprint('agente_plan_bp', __name__)

PERSONALIZATION_GUIDE = """REGRAS DE PERSONALIZAÇÃO DA SEQUÊNCIA:

Por preferência de conteúdo (pref_content_type):
- 'video' → coloque táticas Reuso antes das síncronas ou de envio.
- 'pdf' ou 'leitura' → coloque táticas Reuso com materiais escritos antes das síncronas.
- 'exercicio' ou 'prática' → coloque táticas Reuso com exercícios mais cedo na sequência.

Por preferência de comunicação (pref_communication):
- 'sincrona' ou 'chat' → coloque Debate Síncrono antes de Envio de Informação.
- 'assincrona' ou 'email' → coloque Envio de Informação antes do Debate Síncrono.

Por pref_receive_email:
- true → coloque Envio de Informação antes das atividades práticas.
- false → mova Envio de Informação para o final.

A ordem deve ser personalizada: dois alunos com preferências diferentes devem ter sequências diferentes.

IMPORTANTE: já foi aplicada a tática de Reuso, então NÂO coleque como primeira tática a tatica de reuso novamente. 

Priorize a diversidade de abordagens para reforçar o aprendizado. Também não coloque em sequencia táticas que sejam muito semelhantes entre si, para evitar repetição de atividades.
"""


def _build_groq_client():
    return OpenAI(
        api_key=os.environ.get('GROQ_API_KEY'),
        base_url="https://api.groq.com/openai/v1"
    )


def _collect_student_data(student_id, session_id, session_data):
    """Coleta perfil, notas e histórico do aluno antes de chamar o LLM."""
    profile = {}
    try:
        r = requests.get(f"{USER_URL}/students/{student_id}/preferences", timeout=10)
        if r.status_code == 200:
            d = r.json()
            profile = {
                "course": d.get('course') or 'N/A',
                "age": d.get('age') or 'N/A',
                "pref_content_type": d.get('pref_content_type') or 'N/A',
                "pref_communication": d.get('pref_communication') or 'N/A',
                "pref_receive_email": d.get('pref_receive_email', False),
            }
    except Exception as e:
        logging.warning("Erro ao buscar perfil student_id=%s: %s", student_id, e)

    exercise_scores = None
    verified = [
        v for v in session_data.get('verified_answers', [])
        if str(v.get('student_id', '')) == str(student_id)
    ]
    if verified:
        scores = [v.get('score', 0) for v in verified]
        latest = verified[-1]
        total_q = max(len(latest.get('answers', [])), 1)
        exercise_scores = {
            "attempts": len(scores),
            "scores": scores,
            "latest_score": latest.get('score', 0),
            "latest_total": total_q,
            "latest_pct": int((latest.get('score', 0) / total_q) * 100),
        }

    history = []
    try:
        r = requests.get(
            f"{USER_URL}/students/{student_id}/learning_history",
            params={"limit": 3}, timeout=10
        )
        if r.status_code == 200:
            history = r.json().get('history', [])
    except Exception as e:
        logging.warning("Erro ao buscar histórico student_id=%s: %s", student_id, e)

    return profile, exercise_scores, history


def _call_llm_for_plan(profile, exercise_scores, history, available_tactics, is_replan, student_id):
    """Monta o prompt com todos os dados e faz uma única chamada ao LLM."""
    valid_indices = [t['index'] for t in available_tactics]

    tactics_text = "\n".join(
        f"- Índice {t['index']}: {t['name']} | {str(t.get('description', ''))[:120]}"
        for t in available_tactics
    )

    profile_text = (
        f"Conteúdo preferido: {profile.get('pref_content_type', 'N/A')}\n"
        f"Comunicação preferida: {profile.get('pref_communication', 'N/A')}\n"
        f"Aceita e-mail: {profile.get('pref_receive_email', False)}\n"
        f"Curso: {profile.get('course', 'N/A')} | Idade: {profile.get('age', 'N/A')}"
    ) if profile else "Perfil não disponível."

    scores_text = (
        f"Tentativas: {exercise_scores['attempts']} | Notas: {exercise_scores['scores']} | "
        f"Última: {exercise_scores['latest_score']}/{exercise_scores['latest_total']} ({exercise_scores['latest_pct']}%)"
    ) if exercise_scores else "Sem exercícios respondidos."

    history_text = (
        "\n".join(f"- Sessão {h['session_id']}: {h['summary']}" for h in history)
    ) if history else "Sem histórico de sessões anteriores."

    replan_note = (
        "ATENÇÃO: REPLANEJAMENTO após dificuldades — priorize táticas que reforcem os pontos fracos.\n\n"
        if is_replan else ""
    )

    system_prompt = f"""Você é um especialista em aprendizagem adaptativa. Crie uma sequência personalizada de táticas para um aluno.

{replan_note}{PERSONALIZATION_GUIDE}

TÁTICAS DISPONÍVEIS (índices {valid_indices}):
{tactics_text}

Responda APENAS com JSON válido neste formato exato:
{{
  "tactic_sequence": [lista com TODOS os índices {valid_indices}, cada um UMA vez, na ordem personalizada],
  "overall_goal": "objetivo pedagógico em 1-2 frases",
  "tactic_reasons": {{"indice_como_string": "justificativa baseada no perfil do aluno"}}
}}"""

    user_prompt = f"""PERFIL DO ALUNO:
{profile_text}

DESEMPENHO NOS EXERCÍCIOS DO REUSO:
{scores_text}

HISTÓRICO DE SESSÕES ANTERIORES:
{history_text}

Crie o plano personalizado para as táticas restantes."""

    client = _build_groq_client()
    plan_result = None
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        raw = (response.choices[0].message.content or "").strip()
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > 0:
            plan_result = json.loads(raw[start:end])
    except Exception as e:
        logging.warning("Erro na chamada LLM student_id=%s: %s — usando fallback", student_id, e)

    if not plan_result:
        return {
            "tactic_sequence": valid_indices,
            "overall_goal": "Completar todas as atividades da sessão.",
            "tactic_reasons": {},
        }

    raw_seq = plan_result.get('tactic_sequence', [])
    seen, seq = set(), []
    for i in raw_seq:
        try:
            idx = int(i)
            if idx in valid_indices and idx not in seen:
                seq.append(idx)
                seen.add(idx)
        except (ValueError, TypeError):
            pass
    for idx in valid_indices:
        if idx not in seen:
            seq.append(idx)

    logging.info("Plano gerado: sequence=%s student=%s", seq, student_id)
    return {
        "tactic_sequence": seq,
        "overall_goal": plan_result.get('overall_goal', ''),
        "tactic_reasons": plan_result.get('tactic_reasons', {}),
    }


@agente_plan_bp.route('/orchestrator/agent/replan_session', methods=['POST'])
def replan_session():
    """
    Chamado após o aluno concluir o Reuso. Coleta perfil + notas e pede ao LLM
    a sequência personalizada das táticas restantes em uma única chamada.
    """
    data = request.get_json() or {}
    student_id = data.get('student_id')
    session_id = data.get('session_id')
    is_replan = bool(data.get('is_replan', True))
    completed_tactic_index = data.get('completed_tactic_index')

    if student_id is None or session_id is None:
        return jsonify({"error": "student_id e session_id são obrigatórios"}), 400

    try:
        executed_tactic_indices = []
        try:
            progress_resp = requests.get(
                f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
                timeout=10
            )
            if progress_resp.status_code == 200:
                executed_tactic_indices = list(progress_resp.json().get('executed_tactic_indices', []))
        except Exception as e:
            logging.warning("Erro ao buscar progresso student_id=%s: %s", student_id, e)

        if completed_tactic_index is not None:
            try:
                idx = int(completed_tactic_index)
                if idx not in executed_tactic_indices:
                    executed_tactic_indices.append(idx)
            except (ValueError, TypeError):
                pass

        session_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
        if session_resp.status_code != 200:
            return jsonify({"error": "Falha ao buscar sessão"}), 502
        session_data = session_resp.json()

        strategy_ids = session_data.get('strategies', [])
        strategy_id = strategy_ids[0] if strategy_ids else None
        strategy_tactics = []
        if strategy_id:
            strat_resp = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}", timeout=10)
            if strat_resp.status_code == 200:
                strategy_tactics = strat_resp.json().get('tatics', [])

        if not strategy_tactics:
            return jsonify({"error": "Sem táticas na estratégia"}), 400

        remaining_indices = [i for i in range(len(strategy_tactics)) if i not in executed_tactic_indices]
        if not remaining_indices:
            return jsonify({"message": "Sem táticas restantes para replanejar"}), 200

        available_tactics = [
            {"index": i, "name": strategy_tactics[i].get('name', ''), "description": strategy_tactics[i].get('description', '')}
            for i in remaining_indices
        ]

        profile, exercise_scores, history = _collect_student_data(student_id, session_id, session_data)
        plan = _call_llm_for_plan(profile, exercise_scores, history, available_tactics, is_replan, student_id)

        plan_json = json.dumps({
            "tactic_sequence": plan['tactic_sequence'],
            "overall_goal": plan['overall_goal'],
            "tactic_reasons": plan['tactic_reasons'],
        })

        requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/update_session_plan",
            json={"session_plan": plan_json},
            timeout=10
        )

        logging.info("Plano salvo student_id=%s sequence=%s is_replan=%s",
                     student_id, plan['tactic_sequence'], is_replan)

        return jsonify({
            "new_sequence": plan['tactic_sequence'],
            "overall_goal": plan['overall_goal'],
            "message": "Plano atualizado com sucesso.",
        }), 200

    except Exception as e:
        logging.error("Erro em replan_session student_id=%s: %s", student_id, str(e))
        return jsonify({"error": "Falha no replanejamento"}), 500


@agente_plan_bp.route('/orchestrator/teacher/student_plans', methods=['GET'])
def get_student_plans():
    """Retorna os planos personalizados de todos os alunos de uma sessão."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id é obrigatório"}), 400

    try:
        sess_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
        if sess_resp.status_code != 200:
            return jsonify({"error": "Sessão não encontrada"}), 404
        session_data = sess_resp.json()

        student_ids = session_data.get('students', [])
        strategy_ids = session_data.get('strategies', [])

        tactics_map = {}
        if strategy_ids:
            try:
                sr = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_ids[0]}", timeout=10)
                if sr.status_code == 200:
                    tactics = sr.json().get('tatics', [])
                    tactics_map = {i: t.get('name', f'Tática {i}') for i, t in enumerate(tactics)}
            except Exception:
                pass

        student_names = {}
        if student_ids:
            try:
                nr = requests.get(
                    f"{USER_URL}/students/ids_to_usernames",
                    params={'ids': student_ids},
                    timeout=10
                )
                if nr.status_code == 200:
                    for s in nr.json().get('ids_with_usernames', []):
                        student_names[str(s['id'])] = s['username']
            except Exception:
                pass

        plans = []
        for student_id in student_ids:
            try:
                pr = requests.get(
                    f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
                    timeout=10
                )
                if pr.status_code != 200:
                    continue
                raw_plan = pr.json().get('session_plan')
                if not raw_plan:
                    continue

                plan_data = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
                tactic_sequence = plan_data.get('tactic_sequence', [])
                tactic_reasons = plan_data.get('tactic_reasons', {})

                plans.append({
                    'student_id': str(student_id),
                    'student_name': student_names.get(str(student_id), f'Aluno {student_id}'),
                    'overall_goal': plan_data.get('overall_goal', ''),
                    'tactic_sequence': [
                        {
                            'index': i,
                            'name': tactics_map.get(i, f'Tática {i}'),
                            'reason': tactic_reasons.get(str(i), ''),
                        }
                        for i in tactic_sequence
                    ],
                })
            except Exception as e:
                logging.warning("Erro ao buscar plano student_id=%s: %s", student_id, e)

        return jsonify(plans), 200

    except Exception as e:
        logging.error("Erro em get_student_plans session_id=%s: %s", session_id, e)
        return jsonify({"error": "Falha ao buscar planos"}), 500
