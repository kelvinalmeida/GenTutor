from flask import Blueprint, request, jsonify
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from ...services_routs import STRATEGIES_URL, DOMAIN_URL, CONTROL_URL, USER_URL
from ...auth import token_required
import io
from pypdf import PdfReader

agete_user_bp = Blueprint('agete_user_bp', __name__)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

@agete_user_bp.route('/orchestrator/student/ask_tutor', methods=['POST'])
@token_required
def ask_tutor(current_user):
    """
    Rota reescrita para agregar contexto de estudo e consultar o Agente User.
    """
    try:
        data = request.get_json() or {}
    except:
        return jsonify({"error": "Invalid JSON"}), 400

    user_prompt = data.get('prompt') or data.get('user_prompt')
    if not user_prompt:
        return jsonify({"error": "O campo 'prompt' é obrigatório."}), 400

    username = current_user.get('username') if isinstance(current_user, dict) else current_user
    student_id = current_user.get('id') if isinstance(current_user, dict) else None

    def fetch_grades():
        try:
            # Control service now expects student_id for better accuracy
            target_id = str(student_id) if student_id else '0'
            resp = requests.get(f"{CONTROL_URL}/students/{target_id}/grades_history")
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logging.error(f"Erro ao buscar grades: {e}")
            return {}

    def fetch_chats():
        try:
            resp = requests.get(f"{STRATEGIES_URL}/students/{username}/chat_history")
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logging.error(f"Erro ao buscar chats: {e}")
            return {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_grades = executor.submit(fetch_grades)
        future_chats = executor.submit(fetch_chats)
        grades_resp = future_grades.result()
        chat_resp = future_chats.result()

    # Extract Data from Smart Responses
    if 'raw_history_by_session' in grades_resp:
        raw_grades = grades_resp['raw_history_by_session']
        perf_summary = grades_resp.get('student_performance_summary', 'Sem resumo.')
    else:
        raw_grades = grades_resp
        perf_summary = "Resumo indisponível (Dados antigos ou erro)."

    if 'raw_chat_by_tactic' in chat_resp:
        # raw_chats = chat_resp['raw_chat_by_tactic'] # Unused in simplified view
        eng_summary = chat_resp.get('student_engagement_analysis', 'Sem resumo.')
    else:
        # raw_chats = chat_resp
        eng_summary = "Resumo indisponível (Dados antigos ou erro)."

    study_context = {}
    domain_cache = {}

    # Iterate raw grades to find relevant domains
    for session_id, performance_data in raw_grades.items():
        try:
            sess_resp = requests.get(f"{CONTROL_URL}/sessions/{session_id}")
            if sess_resp.status_code != 200: continue
            session_meta = sess_resp.json()
            domain_ids = session_meta.get('domains', [])
            domain_id = str(domain_ids[0]) if domain_ids else None
            if not domain_id: continue

            if domain_id in domain_cache:
                domain_info = domain_cache[domain_id]
            else:
                dom_resp = requests.get(f"{DOMAIN_URL}/domains/{domain_id}")
                if dom_resp.status_code == 200:
                    domain_info = dom_resp.json()
                    domain_cache[domain_id] = domain_info
                else:
                    domain_info = {"name": "Domínio Desconhecido", "description": "", "pdfs": []}

            domain_name = domain_info.get('name', 'Domínio Sem Nome')

            if domain_name not in study_context:
                processed_pdfs = []
                for pdf in domain_info.get('pdfs', []):
                    pdf_entry = {"filename": pdf.get('filename')}
                    try:
                        pdf_id = pdf.get('id')
                        if pdf_id:
                             pdf_resp = requests.get(f"{DOMAIN_URL}/pdfs/{pdf_id}", timeout=10)
                             if pdf_resp.status_code == 200:
                                 reader = PdfReader(io.BytesIO(pdf_resp.content))
                                 text_preview = ""
                                 if len(reader.pages) > 0:
                                     full_text = reader.pages[0].extract_text() or ""
                                     lines = full_text.split('\n')
                                     text_preview = "\n".join(lines[:10])
                                 pdf_entry["pdf_content"] = text_preview
                             else:
                                 pdf_entry["pdf_content"] = "Não foi possível baixar o conteúdo."
                        else:
                             pdf_entry["pdf_content"] = "ID do PDF não encontrado."
                    except Exception as e:
                        logging.warning(f"Erro ao processar PDF {pdf.get('filename')}: {e}")
                        pdf_entry["pdf_content"] = "Erro na leitura do PDF."
                    processed_pdfs.append(pdf_entry)

                study_context[domain_name] = {
                    "description": domain_info.get('description', ''),
                    "material_complementar": {"pdfs": processed_pdfs},
                    "session_analysis": {
                        "performance": perf_summary,
                        "engagement": eng_summary
                    }
                }

        except Exception as e:
            logging.error(f"Erro ao processar sessão {session_id}: {e}")
            continue

    final_payload = {
        "student_username": username,
        "user_prompt": user_prompt,
        "study_context": study_context
    }

    logging.info(f"Payload final preparado para Agente User: {final_payload}")

    try:
        logging.info(f"Enviando payload para User Service: {USER_URL}/agent/generate_student_feedback")
        agent_resp = requests.post(
            f"{USER_URL}/agent/generate_student_feedback",
            json=final_payload,
            timeout=60
        )
        if agent_resp.status_code == 200:
            return jsonify(agent_resp.json()), 200
        else:
            return jsonify({"error": "Erro no serviço de Agente User", "details": agent_resp.text}), agent_resp.status_code
    except requests.exceptions.RequestException as e:
        logging.error(f"Falha ao contatar Agente User: {e}")
        return jsonify({"error": "Falha na comunicação com o Agente User"}), 503

@agete_user_bp.route('/orchestrator/student/chat_history', methods=['GET'])
@token_required
def get_tutor_chat_history(current_user):
    username = current_user.get('username') if isinstance(current_user, dict) else current_user
    session_id = request.args.get('session_id')
    try:
        params = {'username': username}
        if session_id:
            params['session_id'] = session_id
        resp = requests.get(f"{USER_URL}/agent/chat_history", params=params)
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        return jsonify({"error": "Failed to fetch history"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@agete_user_bp.route('/orchestrator/student/chat_history', methods=['DELETE'])
@token_required
def delete_tutor_chat_history(current_user):
    username = current_user.get('username') if isinstance(current_user, dict) else current_user
    session_id = request.args.get('session_id')
    try:
        params = {'username': username}
        if session_id:
            params['session_id'] = session_id
        resp = requests.delete(f"{USER_URL}/agent/chat_history", params=params)
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        return jsonify({"error": "Failed to delete history"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
