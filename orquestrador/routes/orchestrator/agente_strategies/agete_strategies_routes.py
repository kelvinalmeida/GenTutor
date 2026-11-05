from flask import Blueprint, request, jsonify
import requests
import logging
import json
import sys
import os
from ...services_routs import STRATEGIES_URL, DOMAIN_URL, CONTROL_URL, USER_URL

# Importação robusta das variáveis de serviço (STRATEGIES_URL, DOMAIN_URL)
# Tenta importar relativo, se falhar (devido à profundidade da pasta), ajusta o path.
# try:
#     from routes.services_routs import STRATEGIES_URL, DOMAIN_URL
# except ImportError:
#     # Adiciona o diretório raiz do gateway ao path
#     sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
#     from services_routs import STRATEGIES_URL, DOMAIN_URL

agete_strategies_bp = Blueprint('agete_strategies_bp', __name__)

@agete_strategies_bp.route('/strategies/orchestrate_validation', methods=['POST'])
def orchestrate_validation():
    """
    Agente Orquestrador.
    Fluxo:
    1. Recebe dados do Front.
    2. Busca o conteúdo do Artigo no serviço de Domínio (Memória).
    3. Envia Artigo + Estratégia para o serviço Strategies (Worker com Gemini).
    4. Devolve a resposta para o Front.
    """
    try:
        data = request.json
        strategy_name = data.get('name')
        tactics_names = data.get('tactics', [])

        worker_payload = {
            "name": strategy_name,
            "tactics": tactics_names,
        }

        try:
            agent_response = requests.post(f"{STRATEGIES_URL}/agent/critique", json=worker_payload, timeout=30)
            
            if agent_response.status_code == 200:
                return jsonify(agent_response.json())
            else:
                return jsonify({
                    "grade": 0, 
                    "feedback": f"O Agente de Estratégia falhou. Código: {agent_response.status_code}", 
                    "status": "error"
                }), agent_response.status_code

        except Exception as e:
            logging.error(f"Erro ao conectar com Strategies Agent: {e}")
            return jsonify({
                "grade": 0, 
                "feedback": "Erro de comunicação com o Agente Especialista.", 
                "status": "error"
            }), 503

    except Exception as e:
        return jsonify({"error": "Orchestration failed", "details": str(e)}), 500


@agete_strategies_bp.route('/sessions/<int:session_id>/execute_rules', methods=['POST'])
def execute_rules_logic(session_id):
    """
    Orquestrador da Tática de Regras (por aluno).
    Considera perfil individual do aluno + perfil da turma + desempenho para decisão da IA.
    """
    try:
        data = request.get_json() or {}
        student_id = data.get('student_id')

        # A. Detalhes da Sessão
        try:
            session_response = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=10)
            if session_response.status_code != 200:
                return jsonify({"error": "Falha ao buscar sessão no Control"}), 502
            session_data = session_response.json()
            strategies_list = session_data.get('strategies', [])
            strategy_id = strategies_list[0] if strategies_list else None
            domain_id = int(session_data.get('domains', [None])[0]) if session_data.get('domains') else None
            current_tactic_index = session_data.get('current_tactic_index', 0)
            student_ids = session_data.get('students', [])
        except Exception as e:
            logging.error(f"Erro ao conectar com Control (Sessão): {e}")
            return jsonify({"error": "Control Service unavailable"}), 503

        # B. Resumo de Performance (global da sessão)
        agent_summary_text = "Resumo indisponível."
        try:
            summary_response = requests.get(f"{CONTROL_URL}/sessions/{session_id}/agent_summary", timeout=15)
            if summary_response.status_code == 200:
                agent_summary_text = summary_response.json().get('summary', "")
        except Exception as e:
            logging.warning(f"Erro ao buscar agent_summary: {e}")

        # C. Táticas da Estratégia
        executed_tactics_ids = []
        strategy_tactics = []
        try:
            if strategy_id:
                strat_response = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}", timeout=10)
                if strat_response.status_code == 200:
                    strategy_tactics = strat_response.json().get('tatics', [])
                    executed_indices = session_data.get('executed_indices', [])
                    for idx in executed_indices:
                        if 0 <= idx < len(strategy_tactics):
                            executed_tactics_ids.append(strategy_tactics[idx]['id'])
                    if 0 <= current_tactic_index < len(strategy_tactics):
                        current_id = strategy_tactics[current_tactic_index]['id']
                        if current_id not in executed_tactics_ids:
                            executed_tactics_ids.append(current_id)
        except Exception as e:
            logging.error(f"Erro ao conectar com Strategies: {e}")
            return jsonify({"error": "Strategies Service unavailable"}), 503

        # D. Perfil da Turma
        class_profile_summary = "Perfil da turma desconhecido."
        try:
            if student_ids:
                user_response = requests.post(f"{USER_URL}/students/summarize_preferences", json={"student_ids": student_ids}, timeout=10)
                if user_response.status_code == 200:
                    summary_data = user_response.json().get('summary', "")
                    class_profile_summary = json.dumps(summary_data, ensure_ascii=False) if isinstance(summary_data, dict) else str(summary_data)
        except Exception as e:
            logging.warning(f"Erro ao buscar perfil da turma: {e}")

        # E. Perfil Individual do Aluno
        individual_student_summary = "Perfil individual não disponível."
        if student_id:
            try:
                ind_response = requests.post(f"{USER_URL}/agent/summarize_logged_user", json={"user_id": student_id}, timeout=10)
                if ind_response.status_code == 200:
                    individual_student_summary = ind_response.json().get('summary', "")
            except Exception as e:
                logging.warning(f"Erro ao buscar perfil individual do aluno: {e}")

        # F. Conteúdo do Domínio
        domain_name_and_description = {}
        try:
            if domain_id:
                domain_response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}", timeout=10)
                if domain_response.status_code == 200:
                    domain_name_and_description = {
                        "Conteudo da aula": domain_response.json().get("name", ""),
                        "description do conteúdo da aula": domain_response.json().get("description", "")
                    }
        except Exception as e:
            logging.warning(f"Erro ao conectar com Domain: {e}")

        # G. Notas do Aluno na Sessão
        student_score_summary = "Sem notas registradas para este aluno."
        if student_id:
            verified = [v for v in session_data.get('verified_answers', []) if str(v.get('student_id', '')) == str(student_id)]
            extra = [e for e in session_data.get('extra_notes', []) if str(e.get('student_id', '')) == str(student_id)]

            parts = []
            if verified:
                scores = [v.get('score', 0) for v in verified]
                total_questions = max(len(v.get('answers', [])) for v in verified) or 1
                latest = verified[-1]
                latest_pct = int((latest.get('score', 0) / max(len(latest.get('answers', [])), 1)) * 100)
                parts.append(
                    f"{len(scores)} tentativa(s) nos exercícios. "
                    f"Notas obtidas: {scores}. "
                    f"Última nota: {latest.get('score', 0)}/{max(len(latest.get('answers', [])), 1)} ({latest_pct}%)."
                )
            if extra:
                parts.append(f"Nota extra atribuída pelo professor: {extra[-1].get('extra_notes', 'N/A')}.")

            if parts:
                student_score_summary = " ".join(parts)

        # 2. Consulta à IA de Regras
        decision_payload = {
            "strategy_id": strategy_id,
            "executed_tactics": executed_tactics_ids,
            "performance_summary": agent_summary_text,
            "student_profile_summary": class_profile_summary,
            "individual_student_summary": individual_student_summary,
            "student_score_summary": student_score_summary,
            "article_text": domain_name_and_description,
            "total_tactics": len(strategy_tactics)
        }

        # return jsonify({"received_payload": decision_payload})  # Para debug do payload enviado à IA

        decision_data = {}
        try:
            agent_response = requests.post(f"{STRATEGIES_URL}/agent/decide_rules_logic", json=decision_payload, timeout=30)
            # return jsonify({"decision_data": decision_data})  # Para debug da decisão da IA
            if agent_response.status_code == 200:
                decision_data = agent_response.json().get('rule_execution', {})
            else:
                logging.error(f"Strategies Agent retornou erro: {agent_response.status_code}")
                decision_data = {"decision": "NEXT_STRATEGY", "target_id": None, "reasoning": "Agente indisponível. Avançando por segurança."}
        except Exception as e:
            logging.error(f"Erro ao chamar Strategies Agent: {e}")
            decision_data = {"decision": "NEXT_STRATEGY", "target_id": None, "reasoning": "Erro de conexão com Agente. Avançando."}

        decision = decision_data.get('decision')
        target_id = decision_data.get('target_id')
        reasoning = decision_data.get('reasoning', '')
        action_taken = "Nenhuma ação automática."

        # 3. Execução da Ação (por aluno)
        if decision == "REPEAT_TACTIC" and target_id and student_id:
            target_index = next((i for i, t in enumerate(strategy_tactics) if t['id'] == target_id), -1)
            if target_index >= 0:
                try:
                    # Redireciona o aluno para a tática escolhida (set_tactic reseta should_end_session=FALSE)
                    requests.post(
                        f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/set_tactic",
                        json={"tactic_index": target_index},
                        timeout=5
                    )
                    # Flag: ao concluir essa tática, a sessão encerra automaticamente para o aluno
                    requests.post(
                        f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/set_end_flag",
                        timeout=5
                    )
                    action_taken = f"Aluno redirecionado para tática ID {target_id} (índice {target_index}); sessão encerrará após conclusão"
                except Exception as e:
                    logging.error(f"Erro ao redirecionar tática do aluno: {e}")
            else:
                logging.warning(f"Tática ID {target_id} não encontrada na estratégia atual.")

        elif decision == "NEXT_STRATEGY" and target_id and student_id:
            try:
                requests.post(f"{CONTROL_URL}/sessions/{session_id}/temp_switch_strategy", json={"strategy_id": target_id}, timeout=5)
                requests.post(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/start", timeout=5)
                action_taken = f"Estratégia trocada para ID {target_id} e aluno reiniciado no índice 0"
            except Exception as e:
                logging.error(f"Erro ao trocar estratégia: {e}")

        elif decision == "END_SESSION" and student_id:
            end_index = len(strategy_tactics)
            try:
                requests.post(
                    f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/set_tactic",
                    json={"tactic_index": end_index},
                    timeout=5
                )
                action_taken = "Participação do aluno encerrada (sessão concluída)"
            except Exception as e:
                logging.error(f"Erro ao encerrar participação do aluno: {e}")

        return jsonify({
            "success": True,
            "decision": decision,
            "target_id": target_id,
            "reasoning": reasoning,
            "action_taken": action_taken
        })

    except Exception as e:
        logging.error(f"Erro crítico no execute_rules_logic: {e}")
        return jsonify({"error": "Internal Server Error"}), 500