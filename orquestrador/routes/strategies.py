from flask import Blueprint, render_template, request, jsonify, session, redirect
from requests.exceptions import RequestException
import requests
from .services_routs import STRATEGIES_URL, CONTROL_URL, USER_URL, DOMAIN_URL
from extensions import socketio
from flask_socketio import join_room, leave_room, send, emit
from .auth import token_required
import json


strategy_bp = Blueprint("strategy", __name__)

# Global in-memory storage for online users (Chat ID -> Set of User IDs)
# Note: In a multi-worker production environment, use Redis instead.
connected_users = {}

@strategy_bp.route('/strategies/create', methods=['POST', 'GET'])
def create_strategy():
    if request.method == 'POST':
        # Get the form data
        name = request.form.get("name")
        tatics = request.form.getlist("tatics")
        times = request.form.getlist("times")
        description = request.form.getlist("description")
        domain_ids = request.form.getlist("domain_ids")
        score = request.form.get("score")

        # Junta tática + tempo + domain_id
        tatics_with_times = [
            {
                "name": tatics[i],
                "time": float(times[i]) if times[i] and times[i].strip() else 0.0,
                "description": description[i],
                "domain_id": domain_ids[i] if i < len(domain_ids) and domain_ids[i] else None
            }
            for i in range(len(tatics))
        ]

        # return f"{tatics_with_times}"

        # Um único chat compartilhado por todos os Debates Síncronos da estratégia
        shared_debate_chat_id = None
        for tatics_with_time in tatics_with_times:
            if tatics_with_time["name"] == "Debate Sincrono":
                if shared_debate_chat_id is None:
                    chat_req = requests.post(f"{STRATEGIES_URL}/chat/create")
                    if chat_req.status_code == 200:
                        shared_debate_chat_id = chat_req.json()["id"]
                    else:
                        return jsonify({"error": "Failed to create chat", "details": chat_req.text}), chat_req.status_code
                tatics_with_time["chat_id"] = shared_debate_chat_id
            else:
                tatics_with_time["chat_id"] = None
        
        strategy = {"name": name, "tatics": tatics_with_times, "score": score}
        # return jsonify(strategy)
        
        try:
            response = requests.post(f"{STRATEGIES_URL}/strategies/create", json=strategy)
            if response.status_code == 200:
                # json_response = response.json()
                return render_template("./strategies/success.html")
            else:
                return jsonify({"error": "Failed to create strategy", "details": response.text}), response.status_code
        except RequestException as e:
            return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503
    
    return render_template("./strategies/create_strategy.html")



@strategy_bp.route('/strategies', methods=['GET'])
def get_strategies(current_user=None):
    try:
        response = requests.get(f"{STRATEGIES_URL}/strategies")
        strategies = response.json()  # pega o JSON

        # return jsonify(strategies), 200
        return render_template('./strategies/list_strategies.html', strategies=strategies)
    except RequestException as e:
        return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503
    
    
@strategy_bp.route('/strategies/edit/<int:strategy_id>', methods=['GET', 'POST'])
def edit_strategy(strategy_id):
    if request.method == 'GET':
        try:
            resp_strategy = requests.get(f"{STRATEGIES_URL}/strategies/{strategy_id}")
            resp_domains = requests.get(f"{DOMAIN_URL}/domains")
            resp_strategies = requests.get(f"{STRATEGIES_URL}/strategies")
            strategy = resp_strategy.json()
            domains = resp_domains.json() if resp_domains.ok else []
            available_strategies = resp_strategies.json() if resp_strategies.ok else []
            return render_template(
                './strategies/edit_strategy.html',
                strategy=strategy,
                domains=domains,
                available_strategies=available_strategies
            )
        except RequestException as e:
            return jsonify({"error": str(e)}), 503

    # POST — processa formulário de edição
    name = request.form.get("name")
    tatics = request.form.getlist("tatics")
    times = request.form.getlist("times")
    description = request.form.getlist("description")
    domain_ids = request.form.getlist("domain_ids")
    chat_ids = request.form.getlist("chat_ids")
    score = request.form.get("score", 0)

    # Reutiliza o chat_id já existente entre os Debates Síncronos (ou cria um único novo)
    shared_debate_chat_id = next(
        (chat_ids[i] for i in range(len(tatics))
         if tatics[i] == "Debate Sincrono" and i < len(chat_ids) and chat_ids[i]),
        None
    )

    tatics_with_times = []
    for i in range(len(tatics)):
        domain_id_val = domain_ids[i] if i < len(domain_ids) and domain_ids[i] else None

        if tatics[i] == "Debate Sincrono":
            if not shared_debate_chat_id:
                try:
                    chat_req = requests.post(f"{STRATEGIES_URL}/chat/create")
                    if chat_req.status_code == 200:
                        shared_debate_chat_id = chat_req.json().get("id")
                except Exception:
                    pass
            chat_id_val = shared_debate_chat_id
        else:
            chat_id_val = None

        tatics_with_times.append({
            "name": tatics[i],
            "time": float(times[i]) if i < len(times) and times[i] and times[i].strip() else 0.0,
            "description": description[i] if i < len(description) else "",
            "chat_id": chat_id_val,
            "domain_id": domain_id_val,
        })

    strategy_data = {"name": name, "tatics": tatics_with_times, "score": score}
    try:
        resp = requests.put(f"{STRATEGIES_URL}/strategies/{strategy_id}", json=strategy_data)
        if resp.status_code == 200:
            return redirect('/strategies')
        return jsonify({"error": "Falha ao atualizar estratégia", "details": resp.text}), resp.status_code
    except RequestException as e:
        return jsonify({"error": str(e)}), 503


@strategy_bp.route('/strategies/remove/<int:strategy_id>', methods=['POST'])
def remove_strategy(strategy_id):
    try:
        response = requests.delete(f"{STRATEGIES_URL}/strategies/remove/{strategy_id}")
        if response.status_code == 200:
            # return jsonify({"success": "Strategy removed!"}), 200
            return redirect('/strategies')
        else:
            return jsonify({"error": "Failed to remove strategy", "details": response.text}), response.status_code
    except RequestException as e:
        return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503
    

@strategy_bp.route('/strategies/time/<int:strategy_id>', methods=['GET'])
def get_strategy_time(strategy_id):
    try:
        response = requests.get(f"{STRATEGIES_URL}/strategies/time/{strategy_id}")
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            return jsonify({"error": "Failed to get strategy time", "details": response.text}), response.status_code
    except RequestException as e:
        return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503


@strategy_bp.route('/chat_fragment/<int:chat_id>/<int:session_id>', methods=['GET'])
@token_required
def chat_fragment(chat_id, session_id, current_user=None):
    try:
        # return f"{current_user}"
        # A lógica para buscar usuários permanece a mesma
        response = requests.get(f"{CONTROL_URL}/sessions/{session_id}")
        response.raise_for_status()
        
        session_data = response.json()
        students = session_data.get("students", [])
        teachers = session_data.get("teachers", [])
        
        
        # Uma única chamada para buscar todos os nomes de uma vez é mais eficiente
        teachers = {'ids': teachers}
        students = {'ids': students}
        students_response = requests.get(f"{USER_URL}/students/ids_to_usernames", params=students)
        students_response.raise_for_status()
        teachers_response = requests.get(f"{USER_URL}/teachers/ids_to_usernames", params=teachers)
        teachers_response.raise_for_status()
    
        estudante_usernames = students_response.json()['ids_with_usernames']
        professor_usernames = teachers_response.json()['ids_with_usernames']

        # return f"{estudante_usernames} - {professor_usernames}"

        all_usernames = []

        for estudante in estudante_usernames:
            all_usernames.append(estudante)

        for professor in professor_usernames:
            all_usernames.append(professor)

        # Guarda o ID do usuário na sessão do Flask para uso nos sockets
        
        session['user_id'] = current_user['id']
        session['username'] = current_user['username']

        session['all_users'] = json.dumps(all_usernames)

        # return f"{session['all_users']}"
        
        # Passa a lista de usuários e o usuário atual para o template
        return render_template(
            '/strategies/chat_partial.html', 
            chat_id=chat_id, 
            current_user=current_user
        )
    except RequestException as e:
        return jsonify({"error": "Service unavailable", "details": str(e)}), 503


# --- EVENTOS SOCKET.IO ---

@socketio.on('connect')
def handle_connect():
    # O cliente enviará um evento 'join' após conectar
    print("Cliente conectado")

@socketio.on('join')
def on_join(data):
    """Cliente entra em uma sala específica para este chat."""
    username = session.get('username')
    user_id = session.get('user_id')
    chat_id = data['chat_id']
    
    # Adiciona o cliente à sala do chat
    join_room(chat_id)

    # Add user to connected list
    if chat_id not in connected_users:
        connected_users[chat_id] = set()
    connected_users[chat_id].add(user_id)
    
    # Store chat_id in session for disconnect handler
    session['current_chat_id'] = chat_id

    # Broadcast static list AND online status
    emit('update_user_list', session['all_users'])
    emit('update_online_users', list(connected_users[chat_id]), to=chat_id)
    
@socketio.on('disconnect')
def on_disconnect():
    """Cliente se desconecta e sai da sala."""
    username = session.get('username')
    user_id = session.get('user_id')
    chat_id = session.get('current_chat_id')

    if chat_id and chat_id in connected_users:
        if user_id in connected_users[chat_id]:
            connected_users[chat_id].remove(user_id)
            # Broadcast updated online list
            emit('update_online_users', list(connected_users[chat_id]), to=chat_id)

    # O Flask-SocketIO remove o cliente das salas automaticamente
    print(f'Usuário {username} desconectou.')

@socketio.on('load_general_messages')
def handle_load_general(data):
    """Busca o histórico de mensagens gerais na API."""
    chat_id = data.get('chat_id')
    try:
        response = requests.get(f"{STRATEGIES_URL}/chat/{chat_id}/general_messages")
        response.raise_for_status()
        emit('general_messages_history', response.json())
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            emit('general_messages_history', {"messages": []})
        else:
            emit('error', {"details": f"Não foi possível carregar o histórico geral: {str(e)}"})
    except RequestException as e:
        emit('error', {"details": f"Não foi possível carregar o histórico geral: {str(e)}"})

@socketio.on('load_private_messages')
def handle_load_private(data):
    """Busca o histórico de mensagens privadas entre dois usuários."""
    chat_id = data.get('chat_id')
    user1_id = session.get('user_id')
    user2_id = data.get('with_user_id')
    target_username = data.get('target_username')
    myUsername = session.get('username')

    # emit('private_messages_history', {
    #     "username": session.get('username'),
    #     "content": 'oiii'
    #     }, to=chat_id)
    
    # return
    try:
        response = requests.get(f"{STRATEGIES_URL}/chat/{chat_id}/private_messages/{myUsername}/{target_username}")
        response.raise_for_status()
        print(response.json())
        # Envia o histórico de volta para o cliente que pediu
        emit('private_messages_history', {'target_username': target_username, 'with_user_id': user2_id, 'messages': response.json()})
    except RequestException as e:
        emit('error', {"details": f"Não foi possível carregar o histórico privado: {str(e)}"})
        
@socketio.on('general_message')
def handle_general_message(data):
    """Recebe uma mensagem geral, salva via API e retransmite para a sala."""
    chat_id = data.get('chat_id')
    message_payload = {
        "username": session.get('username'),
        "content": data.get('content')
    }
    try:
        # Salva a mensagem na API
        requests.post(f"{STRATEGIES_URL}/chat/{chat_id}/add_message", json=message_payload)
        # Retransmite para todos na sala
        emit('new_general_message', message_payload, to=chat_id)
    except RequestException as e:
        emit('error', {"details": f"Não foi possível enviar a mensagem: {str(e)}"})

@socketio.on('private_message')
def handle_private_message(data):
    """Recebe uma mensagem privada, salva e a envia para o destinatário correto."""
    chat_id = data.get('chat_id')
    sender_id = session.get('user_id')
    recipient_id = data.get('recipient_id')
    target_username = data.get('target_username')
    # recipient_name = data.get('recipient_name')

    message_payload = {
        "sender_id": sender_id,
        "content": data.get('content'),
        "username": session.get('username'), # Incluindo o nome de quem envia
        "target_username": target_username # Nome do destinatário
    }
    try:
        # Salva a mensagem privada na API
        response = requests.post(f"{STRATEGIES_URL}/chat/{chat_id}/add_priv_message", json=message_payload)
        new_message = response.json() # A API deve retornar a mensagem criada

        # A lógica para enviar ao destinatário específico é complexa sem um mapeamento user->socket.
        # A abordagem mais simples com rooms é enviar para a sala geral e o cliente decide se exibe.
        # O ideal seria ter uma sala por conversa privada (ex: join_room(f'private_{sender_id}_{recipient_id}'))
        emit('new_private_message', new_message, to=chat_id)
        
    except RequestException as e:
        emit('error', {"details": f"Não foi possível enviar a mensagem privada: {str(e)}"})
@strategy_bp.route('/strategies/strategies_json', methods=['GET'])
def get_strategies_json():
    try:
        response = requests.get(f"{STRATEGIES_URL}/strategies")
        strategies = response.json()
        return jsonify(strategies), 200
    except RequestException as e:
        return jsonify({"error": "Strategies service unavailable", "details": str(e)}), 503
