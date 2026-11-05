import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify
from routes.auth import token_required
from routes.services_routs import USER_URL, CONTROL_URL, DOMAIN_URL, STRATEGIES_URL

agente_proactive_orch_bp = Blueprint('agente_proactive_orch_bp', __name__)
logging.basicConfig(level=logging.INFO)


def _get_active_reuso_domain_id(session_id, student_id, session_data):
    """
    Retorna o domain_id da tática Reuso ativa ou mais recentemente executada.
    Varre as táticas do índice atual para trás buscando a mais próxima com
    domain_id preenchido (que indica uma tática Reuso com material associado).
    """
    try:
        strategy_ids = session_data.get('strategies', [])
        if not strategy_ids:
            return None

        prog = requests.get(
            f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index",
            timeout=6
        )
        if prog.status_code != 200:
            return None
        current_index = prog.json().get('current_tactic_index', 0)

        strat = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_ids[0]}", timeout=6)
        if strat.status_code != 200:
            return None
        tactics = strat.json().get('tatics', [])
        if not tactics:
            return None

        # Varre do índice atual para trás buscando a primeira tática com domain_id
        # (táticas Reuso têm domain_id; Debate Sincrono, Envio de Informação, etc. não têm)
        search_start = min(current_index, len(tactics) - 1)
        for i in range(search_start, -1, -1):
            did = tactics[i].get('domain_id')
            if did:
                return did
    except Exception:
        pass
    return None


def _get_session_context(session_id, student_id):
    """
    Agrega contexto anonimizado da sessão para o LLM.
    Retorna: session_domain, session_exercises, pref_content_type.
    Nenhum dado pessoal é incluído no retorno.
    """
    def fetch_domain_context():
        try:
            r = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=6)
            if not r.ok:
                return {}, []
            session_data = r.json() or {}

            # Prioridade 1: domain_id da tática Reuso atual ou mais recente
            # (garante que a dica seja sobre o material em exibição agora)
            domain_id = _get_active_reuso_domain_id(session_id, student_id, session_data)

            # Prioridade 2: primeiro domínio de sessão como fallback
            if not domain_id:
                domain_ids = session_data.get('domains', [])
                domain_id = int(domain_ids[0]) if domain_ids else None

            if not domain_id:
                return {}, []

            # Busca nome e descrição do domínio
            r_domain = requests.get(f"{DOMAIN_URL}/domains/{domain_id}", timeout=6)
            if not r_domain.ok:
                return {}, []
            domain_data = r_domain.json() or {}
            domain_info = {
                "name": domain_data.get('name', ''),
                "description": domain_data.get('description', '')
            }

            # Busca exercícios (apenas enunciados — sem gabarito)
            r_ex = requests.get(f"{DOMAIN_URL}/domains/{domain_id}/exercises", timeout=6)
            questions = []
            if r_ex.ok:
                exercises = r_ex.json()
                if isinstance(exercises, list):
                    questions = [
                        ex.get('question', '')
                        for ex in exercises
                        if ex.get('question')
                    ][:8]

            return domain_info, questions
        except Exception as e:
            logging.warning("Erro ao buscar contexto do domínio session_id=%s: %s", session_id, e)
            return {}, []

    def fetch_pref():
        try:
            r = requests.get(f"{USER_URL}/students/{student_id}", timeout=6)
            if r.ok:
                return r.json().get('pref_content_type', '') or ''
            return ''
        except Exception:
            return ''

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_d = executor.submit(fetch_domain_context)
        f_p = executor.submit(fetch_pref)
        domain_result = f_d.result()
        pref = f_p.result()

    domain_info, questions = domain_result

    return {
        "session_domain": domain_info,
        "session_exercises": questions,
        "pref_content_type": pref
    }


@agente_proactive_orch_bp.route('/orchestrator/student/proactive', methods=['GET'])
@token_required
def get_proactive_recommendation(current_user):
    """
    Gera recomendação proativa focada na sessão atual.
    Agrega contexto anonimizado (maestria, domínio, exercícios) e chama o serviço user.
    Nenhum dado pessoal é enviado ao LLM.
    """
    if current_user.get('type') != 'student':
        return jsonify({"error": "Apenas estudantes podem usar este recurso"}), 403

    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id é obrigatório"}), 400

    student_id = current_user.get('id')
    username = current_user.get('username')

    ctx = _get_session_context(int(session_id), student_id)

    try:
        resp = requests.post(
            f"{USER_URL}/agent/proactive_recommendation",
            json=ctx,
            timeout=20
        )
        if not resp.ok:
            return jsonify({"error": "Falha ao gerar recomendação"}), 502

        recommendation = resp.json().get('recommendation', '')

        # Salva no histórico filtrado por sessão (username só é chave no BD, não vai ao LLM)
        if username and recommendation:
            try:
                requests.post(f"{USER_URL}/agent/save_chat_message", json={
                    "username": username,
                    "sender": "proactive",
                    "message": recommendation,
                    "session_id": int(session_id)
                }, timeout=5)
            except Exception:
                pass

        return jsonify({"recommendation": recommendation}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@agente_proactive_orch_bp.route('/orchestrator/student/floating_chat', methods=['POST'])
@token_required
def floating_chat(current_user):
    """
    Chat da sessão: responde perguntas do estudante com contexto anonimizado da sessão.
    Nenhum dado pessoal (nome, email, username) é enviado ao LLM.
    """
    if current_user.get('type') != 'student':
        return jsonify({"error": "Apenas estudantes podem usar este recurso"}), 403

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    session_id = data.get('session_id')

    if not question:
        return jsonify({"error": "Pergunta vazia"}), 400
    if not session_id:
        return jsonify({"error": "session_id é obrigatório"}), 400

    student_id = current_user.get('id')
    username = current_user.get('username')

    ctx = _get_session_context(int(session_id), student_id)

    # Salva pergunta do estudante no histórico (BD apenas, não vai ao LLM)
    if username:
        try:
            requests.post(f"{USER_URL}/agent/save_chat_message", json={
                "username": username,
                "sender": "user",
                "message": question,
                "session_id": int(session_id)
            }, timeout=5)
        except Exception:
            pass

    # Chama o serviço user com dados anonimizados
    payload = {
        "question": question,
        "session_domain": ctx["session_domain"],
        "session_exercises": ctx["session_exercises"],
        "pref_content_type": ctx["pref_content_type"]
    }

    try:
        resp = requests.post(f"{USER_URL}/agent/chat_answer", json=payload, timeout=20)
        if not resp.ok:
            return jsonify({"error": "Falha ao obter resposta"}), 502

        answer = resp.json().get('answer', '')

        # Salva resposta do agente no histórico
        if username and answer:
            try:
                requests.post(f"{USER_URL}/agent/save_chat_message", json={
                    "username": username,
                    "sender": "agent",
                    "message": answer,
                    "session_id": int(session_id)
                }, timeout=5)
            except Exception:
                pass

        return jsonify({"answer": answer}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
