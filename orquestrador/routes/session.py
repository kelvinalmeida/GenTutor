import json
import logging
import sys
import re
from urllib import response
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from requests.exceptions import RequestException
from flask import Response
import requests
from .auth import token_required
from datetime import datetime
from .services_routs import CONTROL_URL, STRATEGIES_URL, USER_URL, DOMAIN_URL
from .orchestrator.agente_control.agente_control_routes import execute_agent_logic

session_bp = Blueprint("session", __name__)


@session_bp.route('/sessions/create', methods=['GET', "POST"])
@token_required
def create_session(current_user=None):
    if request.method == 'POST':
        try:
            strategy_ids = request.form.getlist('strategies')  # agora é uma lista
            teacher_ids = request.form.getlist('teachers')
            student_ids = request.form.getlist('students')
            domains_ids = request.form.getlist('domains')

            data = {
                "strategies": strategy_ids,
                "teachers": teacher_ids,
                "students": student_ids,
                "domains": domains_ids, 
            }

            response = requests.post(f"{CONTROL_URL}/sessions/create", json=data)

            if response.status_code == 200:
                return render_template("/control/success.html")
            else:
                return f"Erro ao criar sessão: {response.status_code}", response.status_code
        except RequestException as e:
            return jsonify({"error": "Control service unavailable", "details": str(e)}), 503
    else:
        strategies = requests.get(f"{STRATEGIES_URL}/strategies").json()
        teachers = requests.get(f"{USER_URL}/teachers").json()
        students = requests.get(f"{USER_URL}/students").json()
        domains = requests.get(f"{DOMAIN_URL}/domains").json()
        # return f"{domains}"

        return render_template("control/create_session.html", strategies=strategies, teachers=teachers, students=students, domains=domains)


@session_bp.route('/sessions', methods=['GET'])
@token_required
def list_sessions(current_user=None):
    # return current_user
    try:
        # Busca todas as sessões
        response = requests.get(f"{CONTROL_URL}/sessions")
        if response.status_code != 200:
            return f"Erro ao buscar sessões: {response.status_code}", response.status_code

        sessions = response.json()
        # return f"{sessions}"

        # Buscar apenas os nomes das estratégias, professores e alunos
        strategy_data = requests.get(f"{STRATEGIES_URL}/strategies").json()
        teacher_data = requests.get(f"{USER_URL}/teachers").json()
        student_data = requests.get(f"{USER_URL}/students").json()
        domains_data = requests.get(f"{DOMAIN_URL}/domains").json()

        # Mapear apenas os nomes por ID
        strategy_map = {str(item["id"]): item["name"] for item in strategy_data}
        teacher_map = {str(item["id"]): item["username"] for item in teacher_data}
        student_map = {str(item["id"]): item["username"] for item in student_data}
        domains_map = {str(item["id"]): item["name"] for item in domains_data}

        # Mapa: strategy_id → nomes de domínios das táticas Reuso
        strategy_reuso_domains = {}
        for strat in strategy_data:
            reuso_names = []
            for tactic in strat.get("tatics", []):
                if tactic.get("name") == "Reuso" and tactic.get("domain_id"):
                    name = domains_map.get(str(tactic["domain_id"]))
                    if name and name not in reuso_names:
                        reuso_names.append(name)
            if reuso_names:
                strategy_reuso_domains[str(strat["id"])] = reuso_names

        for session in sessions:
            session_strategy_ids = session.get("strategies", [])

            session["strategies"] = [
                strategy_map.get(str(sid), f"ID {sid}")
                for sid in session_strategy_ids
            ]
            session["teachers"] = [
                teacher_map.get(str(tid), f"ID {tid}")
                for tid in session.get("teachers", [])
            ]
            session["students"] = [
                student_map.get(str(sid), f"ID {sid}")
                for sid in session.get("students", [])
            ]

            domain_ids = session.get("domains", [])
            if domain_ids:
                session["domains"] = [
                    domains_map.get(str(sid), f"ID {sid}") for sid in domain_ids
                ]
                session["domains_from_tactic"] = False
            else:
                # Fallback: domínios das táticas Reuso da estratégia
                tactic_domains = []
                for sid in session_strategy_ids:
                    tactic_domains.extend(strategy_reuso_domains.get(str(sid), []))
                session["domains"] = tactic_domains
                session["domains_from_tactic"] = bool(tactic_domains)

        # return f"{sessions}"
        
        return render_template("control/list_all_sessions.html", sessions=sessions, current_user=current_user)

    except RequestException as e:
        return jsonify({"error": "Service unavailable", "details": str(e)}), 503




@session_bp.route('/sessions/<int:session_id>', methods=['GET', 'POST'])
@token_required
def get_session_by_id(session_id, current_user=None):

    if request.method == 'POST':
        response = requests.delete(f"{CONTROL_URL}/sessions/start/{session_id}")
        return (response.text, response.status_code, response.headers.items())

    try:
        # Busca sessão específica no microserviço control
        response = requests.get(f"{CONTROL_URL}/sessions/{session_id}")
        if response.status_code != 200:
            return f"Erro ao buscar sessão: {response.status_code}", response.status_code

        session = response.json()

        params = { 'ids': session.get("strategies", []) }
        strategies = requests.get(f"{STRATEGIES_URL}/strategies/ids_to_names", params=params).json()
        session["strategies"] = strategies  # Adiciona os nomes das estratégias à sessão
    

        all_tatics_time = requests.get(f"{STRATEGIES_URL}/strategies/full_tatics_time", params=params).json()
        session["full_tatics_time"] = all_tatics_time.get("full_tactics_time") # Adiciona o tempo total de táticas à sessão

        teachers_params = { 'ids': session.get("teachers", [])}
        teachers = requests.get(f"{USER_URL}/teachers/ids_to_usernames", params=teachers_params).json()
        session["teachers"] = teachers["usernames"] 

        students_params = { 'ids': session.get("students", [])}
        students = requests.get(f"{USER_URL}/students/ids_to_usernames", params=students_params).json()
        session["students"] = students["usernames"] 

        studantes_with_id_and_username = requests.get(f"{USER_URL}/students").json()
        session["students_ids_with_usernames"] = students['ids_with_usernames']

        domains_params = { 'ids': session.get("domains", [])}
        domains = requests.get(f"{DOMAIN_URL}/domains/ids_to_names", params=domains_params).json()
        session["domains"] = domains

        # Coleta domain_ids das táticas Reuso para disponibilizar PDFs no template
        tactic_domain_ids = []
        for strat in session.get("strategies", []):
            for tatic in strat.get("tatics", []) if isinstance(strat, dict) else []:
                did = tatic.get("domain_id")
                if did and did not in tactic_domain_ids:
                    tactic_domain_ids.append(did)

        tactic_domains_map = {}
        if tactic_domain_ids:
            td_params = {'ids': tactic_domain_ids}
            td_resp = requests.get(f"{DOMAIN_URL}/domains/ids_to_names", params=td_params)
            if td_resp.ok:
                for d in td_resp.json():
                    tactic_domains_map[str(d["id"])] = d

        # return f"{session}"
        return render_template("control/show_session.html", session=session, current_user=current_user,
                               studantes_with_id_and_username=studantes_with_id_and_username,
                               tactic_domains_map=tactic_domains_map)

    except RequestException as e:
        return jsonify({"error": "Service unavailable", "details": str(e)}), 503
    

@session_bp.route('/sessions/enter/', methods=['POST'])
@token_required
def enter_session(current_user=None):

    session_code = request.form.get('session_code')
    requester_id = request.form.get('requester_id')
    type = request.form.get('type')  # 'student' ou 'teacher'

    playload = {
        "session_code": session_code,
        "requester_id": requester_id,
        "type": type
    }

    # return jsonify(playload), 200

    requests.post(f"{CONTROL_URL}/sessions/enter", json=playload)

    return redirect(url_for('session.list_sessions'))


@session_bp.route('/sessions/delete/<int:session_id>', methods=['POST'])
@token_required
def delete_session(session_id, current_user=None):
    if request.form.get('_method') == 'DELETE':
        # Lógica para deletar a sessão
        response = requests.delete(f"{CONTROL_URL}/sessions/delete/{session_id}")
        if response.status_code == 200:
            return redirect(url_for('session.list_sessions'))
        else:
            return f"Erro ao deletar: {response.text}", response.status_code
        

@session_bp.route('/sessions/status/<int:session_id>', methods=['GET'])
@token_required
def get_session_status(session_id, current_user=None):
    try:
        response = requests.get(f"{CONTROL_URL}/sessions/status/{session_id}")
        return jsonify(response.json()), response.status_code
    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503


@session_bp.route('/sessions/start/<int:session_id>', methods=['GET', 'POST'])
@token_required
def start_session(session_id, current_user=None):
    try:
        # Pega dados se for POST (ex: use_agent)
        data = {}
        if request.method == 'POST' and request.is_json:
             data = request.get_json()
        
        # O Control Service já sabe reiniciar (zerar o índice) quando recebe o comando start
        # Repassa o payload (use_agent) para o Control
        response = requests.post(f"{CONTROL_URL}/sessions/start/{session_id}", json=data)
        
        # Verifica se o JSON existe antes de retornar
        try:
            return jsonify(response.json()), response.status_code
        except:
            return response.text, response.status_code

    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503


@session_bp.route('/sessions/end/<int:session_id>', methods=['GET'])
@token_required
def end_session(session_id, current_user=None):
    try:
        response = requests.post(f"{CONTROL_URL}/sessions/end/{session_id}")
        
        # --- CORREÇÃO AQUI ---
        # Não repasse response.headers.items() cegamente, isso pode causar Erro 500 no Flask
        # Retorne apenas o texto e o status code
        return response.text, response.status_code

    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503
    

@session_bp.route('/sessions/<int:session_id>/next_tactic', methods=['POST'])
@token_required
def next_tactic(session_id, current_user=None):
    if current_user and current_user.get('type') != 'teacher':
         return jsonify({"error": "Unauthorized"}), 403

    try:
        # 0. Verifica se o Agente de Estratégia está ativo
        session_res = requests.get(f"{CONTROL_URL}/sessions/{session_id}")
        if session_res.status_code != 200:
            return jsonify({"error": "Failed to fetch session details"}), 500

        session_json = session_res.json()
        use_agent = session_json.get("use_agent", False)
        end_on_next_completion = session_json.get("end_on_next_completion", False)

        # Se houver uma flag de término programada (por regra), IGNORA o agente e força o fluxo normal
        # O fluxo normal (Control/next_tactic) vai detectar a flag e encerrar a sessão.
        if use_agent and not end_on_next_completion:
            # Chama o Orquestrador refatorado
            agent_response = execute_agent_logic(session_id, session_json)
            if agent_response:
                return agent_response

        # === FLUXO NORMAL (LINEAR) OU TÉRMINO PROGRAMADO ===

        # 1. Avança a tática no Microserviço de Controle
        response = requests.post(f"{CONTROL_URL}/sessions/tactic/next/{session_id}")
        if response.status_code != 200:
             return (response.text, response.status_code, response.headers.items())

        # 2. Verifica se a NOVA tática é do tipo "Mudança de Estratégia"
        session_res = requests.get(f"{CONTROL_URL}/sessions/{session_id}")
        if session_res.status_code != 200:
            return jsonify({"error": "Failed to fetch session details"}), 500

        session_json = session_res.json()
        current_tactic_index = session_json.get("current_tactic_index", 0)

        if not session_json.get('strategies'):
            return (response.text, response.status_code, response.headers.items())

        strategy_id = session_json['strategies'][0]


        strategy_res = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}")

        if strategy_res.status_code == 200:
            strategy_data = strategy_res.json()
            tactics = strategy_data.get('tatics', [])

            if 0 <= current_tactic_index < len(tactics):
                current_tactic = tactics[current_tactic_index]
                
                # --- LÓGICA DE DETECÇÃO MELHORADA ---
                tactic_name = current_tactic['name'].strip().lower()
                valid_names = ["mudanca de estrategia", "mudança de estratégia", "mudança de estrategia", "mudanca de estratégia"]

                # Verifica se o nome bate (ignorando maiúsculas/minúsculas)
                if tactic_name in valid_names:
                    description = str(current_tactic.get('description', ''))
                    
                    # Usa Regex para encontrar o primeiro número na descrição (o ID da estratégia)
                    match = re.search(r'\d+', description)

                    if match:
                        target_strategy_id = int(match.group())
                        
                        logging.info(f"Detectada mudança de estratégia para ID: {target_strategy_id}")

                        # Aciona a troca temporária
                        switch_res = requests.post(
                            f"{CONTROL_URL}/sessions/{session_id}/temp_switch_strategy",
                            json={'strategy_id': target_strategy_id}
                        )
                        
                        if switch_res.status_code != 200:
                             logging.error(f"Failed to auto-switch strategy: {switch_res.text}")
                    else:
                        logging.warning(f"Tática '{current_tactic['name']}' ativa, mas nenhum ID numérico encontrado na descrição: '{description}'")

        return (response.text, response.status_code, response.headers.items())
    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/prev_tactic', methods=['POST'])
@token_required
def prev_tactic(session_id, current_user=None):
    if current_user and current_user.get('type') != 'teacher':
         return jsonify({"error": "Unauthorized"}), 403

    try:
        response = requests.post(f"{CONTROL_URL}/sessions/tactic/prev/{session_id}")
        return (response.text, response.status_code, response.headers.items())
    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503


@session_bp.route("/sessions/submit_answer", methods=["POST"])
@token_required
def submit_answer(current_user=None):
    try:
        data = request.get_json()
        student_id = data.get("student_id")
        session_id = data["session_id"]

        # Busca o índice de tática atual do aluno
        tactic_index = 0
        if student_id:
            progress_res = requests.get(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index")
            if progress_res.status_code == 200:
                tactic_index = progress_res.json().get("current_tactic_index", 0)

        # Corrige as respostas do exercício
        verified_answers = requests.post(f"{DOMAIN_URL}/exerc/testscores", json=data).json()

        payload = {
            "student_id": verified_answers["student_id"],
            "student_name": verified_answers["student_name"],
            "session_id": session_id,
            "answers": verified_answers["answers"],
            "score": verified_answers["score"],
            "tactic_index": tactic_index
        }

        logging.info("🔍 submit_answer payload: %s", payload)
        sys.stdout.flush()

        resp = requests.post(f"{CONTROL_URL}/sessions/submit_answer", json=payload)

        if resp.status_code not in [200, 201]:
            return jsonify({"error": "Erro ao salvar resposta no controle", "details": resp.text}), resp.status_code

        resp_data = resp.json()
        passed = resp_data.get("passed", False)
        score = resp_data.get("score", 0)
        student_tactic_index = resp_data.get("student_tactic_index", tactic_index)

        total = len(data.get('answers') or []) or 1
        pct = int((score / total) * 100)
        if passed:
            msg = f"Parabéns! Você acertou {score}/{total} questões ({pct}%) e avançou para a próxima tática."
        else:
            msg = f"Você acertou {score}/{total} questões ({pct}%). São necessários 70% para avançar. Tente novamente!"

        return jsonify({
            "resp": msg,
            "passed": passed,
            "score": score,
            "student_tactic_index": student_tactic_index
        }), 200

    except Exception as e:
        import traceback
        logging.info("❌ Erro interno no servidor:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    

@session_bp.route("/studant/extranotes/<int:student_id>", methods=["POST"])
@token_required
def add_extra_notes(student_id, current_user=None):
    data = request.form.get("extra_notes")
    session_id = request.form.get("session_id")

    student = requests.get(f"{USER_URL}/students/{student_id}").json()

    playload = {
        "student_id": student.get("id"),
        "estudante_username": student.get("username"),
        "extra_notes": float(data),
        "session_id": session_id,
    }

    requests.post(f"{CONTROL_URL}/sessions/add_extra_notes", json=playload)

    return Response(status=204)
  

@session_bp.route('/sessions/<int:session_id>/student_start', methods=['POST'])
@token_required
def student_start_own(session_id, current_user=None):
    if not current_user or current_user.get('type') != 'student':
        return jsonify({"error": "Apenas alunos podem iniciar seu próprio percurso"}), 403
    student_id = current_user.get('id')
    try:
        resp = requests.post(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/start")
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return resp.text, resp.status_code
    except RequestException as e:
        return jsonify({"error": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/student_advance_tactic', methods=['POST'])
@token_required
def student_advance_tactic(session_id, current_user=None):
    if not current_user or current_user.get('type') != 'student':
        return jsonify({"error": "Apenas alunos podem avançar sua própria tática"}), 403
    student_id = current_user.get('id')
    try:
        resp = requests.post(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/advance_tactic")
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return resp.text, resp.status_code
    except RequestException as e:
        return jsonify({"error": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/student_change_strategy', methods=['POST'])
@token_required
def student_change_strategy(session_id, current_user=None):
    if not current_user or current_user.get('type') != 'student':
        return jsonify({"error": "Apenas alunos podem fazer esta ação"}), 403
    student_id = current_user.get('id')
    data = request.get_json() or {}
    new_strategy_id = data.get('strategy_id')
    if not new_strategy_id:
        return jsonify({"error": "strategy_id é obrigatório"}), 400
    try:
        switch_res = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/temp_switch_strategy",
            json={'strategy_id': new_strategy_id}
        )
        if switch_res.status_code != 200:
            return jsonify({"error": "Falha ao mudar estratégia"}), 500
        # Reset individual student's tactic index to 0
        requests.post(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/start")
        return jsonify({"success": True}), 200
    except RequestException as e:
        return jsonify({"error": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/current_tactic', methods=['GET'])
def get_current_tactic(session_id):
    student_id = request.args.get('student_id')

    session_response = requests.get(f"{CONTROL_URL}/sessions/{session_id}")

    if session_response.status_code != 200:
        return jsonify({'error': 'Session not found'}), 404

    session_json = session_response.json()

    adaptive_tactic_enabled = session_json.get('adaptive_tactic_enabled', False)

    if session_json['status'] != 'in-progress':
        return jsonify({
            'message': 'Session not started or finished',
            'session_status': session_json['status'],
            'adaptive_tactic_enabled': adaptive_tactic_enabled
        }), 200

    # Índice e timer de tática: individual por aluno, ou global para professor
    student_tactic_started_at = None
    if student_id:
        progress_res = requests.get(f"{CONTROL_URL}/sessions/{session_id}/student/{student_id}/tactic_index")
        if progress_res.status_code == 200:
            prog = progress_res.json()
            if not prog.get("student_started", True):
                return jsonify({'session_status': 'not_started', 'adaptive_tactic_enabled': adaptive_tactic_enabled})
            current_tactic_index = prog.get("current_tactic_index", 0)
            student_tactic_started_at = prog.get("tactic_started_at")
        else:
            current_tactic_index = session_json.get("current_tactic_index", 0)
    else:
        current_tactic_index = session_json.get("current_tactic_index", 0)

    # Fetch all tactics
    tactics = []
    current_strategy_id = None
    if session_json['strategies']:
         current_strategy_id = session_json['strategies'][0]
         strategy_response = requests.get(f"{STRATEGIES_URL}/strategies/{current_strategy_id}")
         if strategy_response.status_code == 200:
             strategy_data = strategy_response.json()
             tactics = strategy_data.get('tatics', [])

    # Check bounds
    if current_tactic_index >= len(tactics):
        if student_id:
            # Aluno terminou todas as suas táticas — não encerra a sessão global
            return jsonify({'message': 'No more tactics', 'session_status': 'student_finished'})

        # Visão global (professor): encerra a sessão para todos
        if session_json['status'] == 'in-progress':
            logging.info(f"Fim das táticas atingido para a sessão {session_id}. Encerrando automaticamente.")
            requests.post(f"{CONTROL_URL}/sessions/end/{session_id}")
            session_json['status'] = 'finished'

        return jsonify({'message': 'No more tactics', 'session_status': 'finished'})

    current_tactic = tactics[current_tactic_index]

    # Calculate Remaining Time
    # Assuming current_tactic_started_at is in session_json
    # It might be None if the session was created before migration or if start_session didn't set it (but I updated it)
    # The format coming from Postgres might need parsing.

    remaining = 0
    elapsed_time = 0
    
    # Timer individual do aluno; fallback para o timer global da sessão
    started_at_str = student_tactic_started_at or session_json.get("current_tactic_started_at")

    if started_at_str:
        try:
             # Try parsing format. Python default isoformat or Postgres string
             # "Tue, 05 Nov 2024 18:30:00 GMT" or ISO
             # The Control service uses datetime.utcnow() so it might be returned as string in JSON
             # Check if it is the RFC format used in start_time or ISO

             # Parse date string from Control service
             # Supported formats:
             # 1. RFC 1123 (e.g., "Fri, 19 Dec 2025 20:20:27 GMT") - Default for Flask jsonify
             # 2. ISO 8601 with microseconds (e.g., "2024-11-05T18:30:00.123456")
             # 3. ISO 8601 without microseconds (e.g., "2024-11-05T18:30:00")
             # 4. Postgres simple format (e.g., "2024-11-05 18:30:00")

             try:
                 started_at = datetime.strptime(started_at_str, "%a, %d %b %Y %H:%M:%S %Z")
             except ValueError:
                 try:
                     started_at = datetime.strptime(started_at_str, "%Y-%m-%dT%H:%M:%S.%f")
                 except ValueError:
                     try:
                         started_at = datetime.strptime(started_at_str, "%Y-%m-%dT%H:%M:%S")
                     except ValueError:
                         started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S")

             elapsed_time = (datetime.utcnow() - started_at).total_seconds()
             duration_seconds = current_tactic.get('time', 0) * 60
             remaining = max(0, duration_seconds - elapsed_time)

        except Exception as e:
            logging.error(f"Error parsing date: {e}")
            remaining = current_tactic.get('time', 0) * 60 # Fallback
    else:
        # Fallback logic if `current_tactic_started_at` is missing (legacy sessions)
        # We could default to the old logic or just show full time
        remaining = current_tactic.get('time', 0) * 60

    return jsonify({
        'tactic': {
            'name': current_tactic['name'],
            'description': current_tactic.get('description', ''),
            'domain_id': current_tactic.get('domain_id'),
            'total_time': current_tactic.get('time', 0) * 60
        },
        'remaining_time': int(remaining),
        'elapsed_time': int(elapsed_time),
        'strategy_tactics': tactics,
        'session_status': session_json['status'],
        'current_tactic_index': current_tactic_index,
        'strategy_id': current_strategy_id,
        'adaptive_tactic_enabled': session_json.get('adaptive_tactic_enabled', False)
    })


@session_bp.route('/sessions/<int:session_id>/set_adaptive_tactic', methods=['POST'])
@token_required
def set_adaptive_tactic(session_id, current_user=None):
    if current_user and current_user.get('type') != 'teacher':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json() or {}
    try:
        resp = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/set_adaptive_tactic",
            json=data,
            timeout=10
        )
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return resp.text, resp.status_code
    except RequestException as e:
        return jsonify({"error": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/change_strategy', methods=['POST'])
@token_required
def change_strategy(session_id, current_user=None):
    if current_user and current_user.get('type') != 'teacher':
         return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json()
        strategy_id = data.get('strategy_id')

        if not strategy_id:
             return jsonify({"error": "Strategy ID is required"}), 400

        # Call Control Service to update
        response = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/change_strategy",
            json={'strategy_id': strategy_id}
        )

        if response.status_code == 200:
             return jsonify(response.json()), 200
        else:
             return jsonify({"error": "Failed to update strategy", "details": response.text}), response.status_code

    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503

@session_bp.route('/sessions/<int:session_id>/change_domain', methods=['POST'])
@token_required
def change_domain(session_id, current_user=None):
    if current_user and current_user.get('type') != 'teacher':
         return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json()
        domain_id = data.get('domain_id')

        if not domain_id:
             return jsonify({"error": "Domain ID is required"}), 400

        # Call Control Service to update
        response = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/change_domain",
            json={'domain_id': domain_id}
        )

        if response.status_code == 200:
             return jsonify(response.json()), 200
        else:
             return jsonify({"error": "Failed to update domain", "details": response.text}), response.status_code

    except RequestException as e:
        return jsonify({"error": "Control service unavailable", "details": str(e)}), 503

@session_bp.route('/sessions/<int:session_id>/rate', methods=['POST'])
@token_required
def rate_session(session_id, current_user=None):
    if not current_user:
        return jsonify({"error": "Unauthorized"}), 401

    if current_user.get('type') != 'student':
        return jsonify({"error": "Only students can vote"}), 403

    try:
        data = request.get_json()
        payload = {
            'student_id': current_user.get('id'),
            'rating': data.get('rating')
        }

        response = requests.post(f"{CONTROL_URL}/sessions/{session_id}/rate", json=payload)
        # Tenta retornar JSON se possível
        try:
            return jsonify(response.json()), response.status_code
        except:
            return (response.text, response.status_code, response.headers.items())
    except RequestException as e:
        return jsonify({"error": "Service unavailable", "details": str(e)}), 503

@session_bp.route('/sessions/<int:session_id>/rating', methods=['GET'])
@token_required
def get_session_rating(session_id, current_user=None):
    try:
        params = {}
        if current_user and current_user.get('type') == 'student':
            params['student_id'] = current_user.get('id')

        response = requests.get(f"{CONTROL_URL}/sessions/{session_id}/rating", params=params)
        try:
            return jsonify(response.json()), response.status_code
        except:
            return (response.text, response.status_code, response.headers.items())
    except RequestException as e:
        return jsonify({"error": "Service unavailable", "details": str(e)}), 503


@session_bp.route('/sessions/<int:session_id>/teacher_alerts', methods=['GET'])
@token_required
def get_teacher_alerts(session_id, current_user=None):
    try:
        response = requests.get(f"{STRATEGIES_URL}/sessions/{session_id}/alerts", timeout=10)
        return jsonify(response.json()), response.status_code
    except RequestException as e:
        return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503
