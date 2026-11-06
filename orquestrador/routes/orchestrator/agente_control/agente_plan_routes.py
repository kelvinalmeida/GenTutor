import json
import logging
import os
from collections import Counter

import requests
from flask import Blueprint, jsonify, request
from openai import OpenAI
from ...services_routs import CONTROL_URL, DOMAIN_URL, STRATEGIES_URL, USER_URL

logging.basicConfig(level=logging.INFO)

agente_plan_bp = Blueprint('agente_plan_bp', __name__)

PERSONALIZATION_GUIDE = """REGRAS DE PERSONALIZAÇÃO DA SEQUÊNCIA:
Como já foi aplicada a tática de Reuso, não coloque como primeira tática as que são mais semelhantes ao Reuso.
Priorize a diversidade de abordagens para reforçar o aprendizado.

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
Use a estratégia do professor como referência e o perfil da turma apenas como contexto; a decisão é individual."""

# APÊNDICE D do TCC: linha acrescentada ao prompt no replanejamento
REPLAN_NOTE = "ATENÇÃO: REPLANEJAMENTO após dificuldades — priorize táticas que reforcem os pontos fracos."

REPLAN_DECISION_GUIDE = """DECISÃO DE REPLANEJAMENTO:
O aluno acabou de concluir uma tática de Reuso intermediária com exercícios. Avalie o desempenho dele nessa tática
e decida se a ordem atual das táticas restantes deve ser reorganizada.
- Se o aluno teve dificuldade (precisou de mais de uma tentativa ou teve nota baixa), reorganize para priorizar
  os conteúdos em que ele demonstrou dificuldade e responda "replan_needed": true.
- Se o desempenho foi bom, mantenha a ordem atual e responda "replan_needed": false.
- Coerência obrigatória: se responder "replan_needed": true, a "tactic_sequence" DEVE ser diferente da ordem atual.
  Se concluir que a ordem atual já é a melhor, responda "replan_needed": false.
As táticas já concluídas não fazem parte do replanejamento."""


def _build_groq_client():
    return OpenAI(
        api_key=os.environ.get('GROQ_API_KEY'),
        base_url="https://api.groq.com/openai/v1"
    )


def _collect_student_data(student_id, session_data, completed_tactic_index=None):
    """Coleta perfil, desempenho no exercício e histórico do aluno (sem dados que o identifiquem)."""
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

    # Exercício que o aluno acabou de realizar (a tática de Reuso concluída)
    exercise_scores = None
    verified = [
        v for v in session_data.get('verified_answers', [])
        if str(v.get('student_id', '')) == str(student_id)
    ]
    if completed_tactic_index is not None:
        same_tactic = [v for v in verified if str(v.get('tactic_index')) == str(completed_tactic_index)]
        verified = same_tactic or verified
    if verified:
        latest = verified[-1]
        total_q = max(len(latest.get('answers', [])), 1)
        scores = latest.get('score_history') or [latest.get('score', 0)]
        exercise_scores = {
            "attempts": latest.get('attempts') or len(scores),
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


def _collect_class_profile(session_data):
    """Perfil da turma: preferências agregadas dos alunos da sessão (sem nomes)."""
    student_ids = session_data.get('students', [])
    if not student_ids:
        return None
    try:
        r = requests.post(
            f"{USER_URL}/students/batch_preferences",
            json={"student_ids": student_ids}, timeout=10
        )
        if r.status_code != 200:
            return None
        students = r.json().get('students', [])
    except Exception as e:
        logging.warning("Erro ao buscar perfil da turma: %s", e)
        return None
    if not students:
        return None

    def _count(key):
        c = Counter('N/A' if s.get(key) in (None, '') else str(s.get(key)) for s in students)
        return ", ".join(f"{k}: {v}" for k, v in c.most_common())

    return {
        "total": len(students),
        "pref_content_type": _count('pref_content_type'),
        "pref_communication": _count('pref_communication'),
        "pref_receive_email": _count('pref_receive_email'),
    }


def _collect_domain_info(session_data, strategy_tactics):
    """Nome e descrição dos domínios usados na sessão (da sessão e das táticas de Reuso)."""
    domain_ids = [d for d in session_data.get('domains', []) if d]
    for t in strategy_tactics:
        if t.get('domain_id') and t.get('domain_id') not in domain_ids:
            domain_ids.append(t.get('domain_id'))
    domains = []
    for domain_id in domain_ids:
        try:
            r = requests.get(f"{DOMAIN_URL}/domains/{domain_id}", timeout=10)
            if r.status_code == 200:
                d = r.json()
                domains.append({"name": d.get('name', ''), "description": d.get('description', '')})
        except Exception as e:
            logging.warning("Erro ao buscar domínio %s: %s", domain_id, e)
    return domains


def _call_llm_for_plan(profile, exercise_scores, history, available_tactics, is_replan, student_id,
                       class_profile=None, strategy_tactics=None, domains=None, current_order=None,
                       correction=None):
    """Monta o prompt com todos os dados e faz uma chamada ao LLM.
    `correction`: aviso extra enviado quando a resposta anterior foi incoerente."""
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

    class_text = (
        f"Alunos na sessão: {class_profile['total']}\n"
        f"Conteúdo preferido: {class_profile['pref_content_type']}\n"
        f"Comunicação preferida: {class_profile['pref_communication']}\n"
        f"Aceita e-mail: {class_profile['pref_receive_email']}"
    ) if class_profile else "Perfil da turma não disponível."

    strategy_text = (
        " → ".join(f"{i}: {t.get('name', '')}" for i, t in enumerate(strategy_tactics))
    ) if strategy_tactics else "Não disponível."

    domain_text = (
        "\n".join(f"- {d['name']}: {str(d.get('description') or '')[:200]}" for d in domains)
    ) if domains else "Não disponível."

    replan_block = f"{REPLAN_NOTE}\n\n{REPLAN_DECISION_GUIDE}\n\n" if is_replan else ""
    replan_field = (
        '\n  "replan_needed": true ou false,'
        '\n  "replan_reason": "motivo da decisão em 1-2 frases, dirigido ao aluno (use \'você\')",'
    ) if is_replan else ""

    system_prompt = f"""Você é um especialista em aprendizagem adaptativa. Crie uma sequência personalizada de táticas para um aluno.

{replan_block}{PERSONALIZATION_GUIDE}

TÁTICAS DISPONÍVEIS (índices {valid_indices}):
{tactics_text}

Responda APENAS com JSON válido neste formato exato:
{{{replan_field}
  "tactic_sequence": [lista com TODOS os índices {valid_indices}, cada um UMA vez, na ordem personalizada],
  "overall_goal": "objetivo pedagógico em 1-2 frases",
  "tactic_reasons": {{"indice_como_string": "justificativa baseada no perfil do aluno"}}
}}"""

    current_order_text = (
        f"\n\nORDEM ATUAL DAS TÁTICAS RESTANTES NO PLANO: {current_order}"
        if is_replan and current_order else ""
    )

    user_prompt = f"""PERFIL DO ALUNO:
{profile_text}

DESEMPENHO NOS EXERCÍCIOS DO REUSO:
{scores_text}

HISTÓRICO DE SESSÕES ANTERIORES:
{history_text}

PERFIL DA TURMA:
{class_text}

ESTRATÉGIA DO PROFESSOR (sequência original):
{strategy_text}

DOMÍNIO DA SESSÃO:
{domain_text}{current_order_text}

Crie o plano personalizado para as táticas restantes."""
    if correction:
        user_prompt += f"\n\n{correction}"

    client = _build_groq_client()
    plan_result = None
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
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
            "replan_needed": False,
            "replan_reason": "Não foi possível analisar seu desempenho agora, então seu plano atual foi mantido.",
            "tactic_sequence": current_order or valid_indices,
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

    replan_needed = plan_result.get('replan_needed', True)
    if isinstance(replan_needed, str):
        replan_needed = replan_needed.strip().lower() in ('true', 'sim', 'yes', '1')

    logging.info("Plano gerado: sequence=%s student=%s replan_needed=%s", seq, student_id, replan_needed)
    return {
        "replan_needed": bool(replan_needed),
        "replan_reason": str(plan_result.get('replan_reason') or '').strip(),
        "tactic_sequence": seq,
        "overall_goal": plan_result.get('overall_goal', ''),
        "tactic_reasons": plan_result.get('tactic_reasons', {}),
    }


@agente_plan_bp.route('/orchestrator/agent/replan_session', methods=['POST'])
def replan_session():
    """
    Chamado ao concluir uma tática de Reuso com exercícios.

    - 1º Reuso (aluno ainda sem plano): planejamento individualizado da sessão.
    - Reuso intermediário (aluno já tem plano): a IA decide se reorganiza as táticas
      restantes; as táticas já concluídas são preservadas.
    Ocorre quando o aluno atinge 70% ou esgota as tentativas da avaliação.
    """
    data = request.get_json() or {}
    student_id = data.get('student_id')
    session_id = data.get('session_id')
    completed_tactic_index = data.get('completed_tactic_index')

    if student_id is None or session_id is None:
        return jsonify({"error": "student_id e session_id são obrigatórios"}), 400

    try:
        executed_tactic_indices = []
        existing_plan = None
        try:
            progress_resp = requests.get(
                f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
                timeout=10
            )
            if progress_resp.status_code == 200:
                prog = progress_resp.json()
                executed_tactic_indices = list(prog.get('executed_tactic_indices', []))
                raw_plan = prog.get('session_plan')
                if raw_plan:
                    existing_plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        except Exception as e:
            logging.warning("Erro ao buscar progresso student_id=%s: %s", student_id, e)

        # O servidor decide se é planejamento inicial ou replanejamento: depende de já existir um plano
        existing_seq = (existing_plan or {}).get('tactic_sequence') or []
        is_replan = bool(existing_seq)

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

        # Ordem atual das táticas restantes segundo o plano vigente
        current_order = [i for i in existing_seq if i in remaining_indices]
        current_order += [i for i in remaining_indices if i not in current_order]

        available_tactics = [
            {"index": i, "name": strategy_tactics[i].get('name', ''), "description": strategy_tactics[i].get('description', '')}
            for i in remaining_indices
        ]

        profile, exercise_scores, history = _collect_student_data(student_id, session_data, completed_tactic_index)
        class_profile = _collect_class_profile(session_data)
        domains = _collect_domain_info(session_data, strategy_tactics)

        plan = _call_llm_for_plan(
            profile, exercise_scores, history, available_tactics, is_replan, student_id,
            class_profile=class_profile, strategy_tactics=strategy_tactics, domains=domains,
            current_order=current_order if is_replan else None,
        )

        # A IA pode dizer que replaneja e mesmo assim devolver a mesma ordem. Pede de novo uma vez,
        # apontando a incoerência; se repetir, trata como plano mantido para o aviso ao aluno ser verdadeiro.
        if is_replan and plan['replan_needed'] and plan['tactic_sequence'] == current_order:
            logging.info("IA indicou replanejamento mas repetiu a ordem %s (student_id=%s); nova tentativa",
                         current_order, student_id)
            plan = _call_llm_for_plan(
                profile, exercise_scores, history, available_tactics, is_replan, student_id,
                class_profile=class_profile, strategy_tactics=strategy_tactics, domains=domains,
                current_order=current_order,
                correction=(
                    f"ATENÇÃO: na resposta anterior você indicou \"replan_needed\": true, mas devolveu a mesma ordem "
                    f"atual {current_order}. Se o replanejamento é necessário, devolva uma ordem DIFERENTE de "
                    f"{current_order} que reforce os pontos de dificuldade. Se a ordem atual já é a melhor, "
                    f"responda \"replan_needed\": false e explique o motivo."
                ),
            )
            if plan['replan_needed'] and plan['tactic_sequence'] == current_order:
                plan['replan_needed'] = False
                plan['replan_reason'] = (
                    "Você teve dificuldade nessa tática, mas a ordem das próximas atividades já é a mais "
                    "adequada para reforçar esses conteúdos, então ela foi mantida."
                )

        if is_replan and not plan['replan_needed']:
            logging.info("Replanejamento dispensado pela IA student_id=%s; mantendo ordem %s",
                         student_id, current_order)
            return jsonify({
                "is_replan": True,
                "replanned": False,
                "replan_reason": plan.get("replan_reason") or "Seu desempenho foi adequado, então o plano atual foi mantido.",
                "new_sequence": existing_seq,
                "overall_goal": existing_plan.get('overall_goal', ''),
                "message": "Desempenho adequado: plano mantido.",
            }), 200

        # Preserva o progresso: táticas já concluídas (incluindo o 1º Reuso) ficam no início do plano,
        # para aparecerem como concluídas na sequência mostrada ao aluno e ao professor
        done_prefix = [i for i in existing_seq if i in executed_tactic_indices]
        done_prefix += [i for i in executed_tactic_indices if i not in done_prefix]
        full_sequence = done_prefix + plan['tactic_sequence']

        reasons = dict((existing_plan or {}).get('tactic_reasons', {})) if is_replan else {}
        reasons.update(plan['tactic_reasons'] or {})

        plan_json = json.dumps({
            "tactic_sequence": full_sequence,
            "overall_goal": plan['overall_goal'],
            "tactic_reasons": reasons,
        })

        requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/update_session_plan",
            json={"session_plan": plan_json},
            timeout=10
        )

        logging.info("Plano salvo student_id=%s sequence=%s is_replan=%s",
                     student_id, full_sequence, is_replan)

        return jsonify({
            "is_replan": is_replan,
            "replanned": is_replan,
            "replan_reason": (plan.get("replan_reason") or "As próximas atividades foram reorganizadas para reforçar os pontos em que você teve dificuldade.") if is_replan else "",
            "new_sequence": full_sequence,
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
