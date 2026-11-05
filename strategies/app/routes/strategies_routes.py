from operator import or_
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
# from app.models import Strategies, Tatics, Message, PrivateMessage
# from app import db  # importar o socketio criado no __init__.py
from db import create_connection
import json

strategies_bp = Blueprint('strategies_bp', __name__)

# @strategies_bp.before_app_request
# def create_tables():
#     db.create_all()

@strategies_bp.route('/strategies/create', methods=['POST', 'GET'])
def create_strategy():
    # Proteção básica: Se for GET, o request.json pode não existir ou ser None.
    # Assumindo que a criação ocorre no POST.
    if request.method != 'POST':
        return jsonify({"error": "Method not allowed"}), 405

    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        name = request.json.get('name')
        raw_tatics = request.json.get('tatics', [])
        score = request.json.get('score', 0)

        # Insert strategy
        query_strat = "INSERT INTO strategies (name, score) VALUES (%s, %s) RETURNING id;"
        cursor.execute(query_strat, (name, score))
        strategy_id = cursor.fetchone()['id']

        # Insert tactics
        if raw_tatics:
            query_tactic = """
                INSERT INTO tactics (name, description, time, chat_id, strategy_id, domain_id)
                VALUES (%s, %s, %s, %s, %s, %s);
            """
            for tatic in raw_tatics:
                domain_id_val = tatic.get("domain_id")
                cursor.execute(query_tactic, (
                    tatic.get("name"),
                    tatic.get("description"),
                    tatic.get("time"),
                    tatic.get("chat_id"),
                    strategy_id,
                    int(domain_id_val) if domain_id_val else None
                ))
        
        conn.commit()
        cursor.close()
        conn.close()

        # Saída idêntica à original
        return jsonify({"success": "Strategie created!"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400


# @strategies_bp.route('/strategies', methods=['GET'])
# def list_strategies():
#     all_strategies = Strategies.query.all()
#     return jsonify([{"id": s.id, "name": s.name, "tatics": [t.as_dict() for t in s.tatics]} for s in all_strategies]), 200

@strategies_bp.route('/strategies', methods=['GET'])
def list_strategies():
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Seleciona estratégias
        query = "SELECT id, name, score FROM strategies;"
        cursor.execute(query)
        strategies = cursor.fetchall()

        # Popula tatics para cada estratégia
        # (N+1 query, mas mantém simplicidade com psycopg2 raw)
        for s in strategies:
            cursor.execute("SELECT id, name, description, time, chat_id, domain_id FROM tactics WHERE strategy_id = %s", (s['id'],))
            s['tatics'] = cursor.fetchall()

        cursor.close()
        conn.close()

        # Retornamos direto, pois a estrutura já é compatível com JSON
        return jsonify(strategies), 200

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 400

# @strategies_bp.route('/strategies/<int:strategy_id>', methods=['GET'])
# def strategy_by_id(strategy_id):
#     strategy = Strategies.query.get(strategy_id)
#     if strategy:
#         return jsonify({"id": strategy.id, "name": strategy.name, "tatics": [t.as_dict() for t in strategy.tatics]}), 200
#     return jsonify({"error": "Strategy not found"}), 404

@strategies_bp.route('/strategies/<int:strategy_id>', methods=['GET'])
def strategy_by_id(strategy_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Seleciona a estratégia específica pelo ID
        query = "SELECT id, name, score FROM strategies WHERE id = %s"
        cursor.execute(query, (strategy_id,))
        strategy = cursor.fetchone()

        if strategy:
            cursor.execute("SELECT id, name, description, time, chat_id, domain_id FROM tactics WHERE strategy_id = %s", (strategy['id'],))
            strategy['tatics'] = cursor.fetchall()

            cursor.close()
            conn.close()
            return jsonify(strategy), 200
        
        cursor.close()
        conn.close()
        return jsonify({"error": "Strategy not found"}), 404

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 400


@strategies_bp.route('/strategies/<int:strategy_id>', methods=['PUT'])
def update_strategy(strategy_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    cursor = conn.cursor()
    try:
        data = request.get_json()
        name = data.get('name')
        score = data.get('score', 0)
        tatics = data.get('tatics', [])

        cursor.execute("UPDATE strategies SET name = %s, score = %s WHERE id = %s", (name, score, strategy_id))
        cursor.execute("DELETE FROM tactics WHERE strategy_id = %s", (strategy_id,))

        if tatics:
            query_tactic = """
                INSERT INTO tactics (name, description, time, chat_id, strategy_id, domain_id)
                VALUES (%s, %s, %s, %s, %s, %s);
            """
            for tatic in tatics:
                domain_id_val = tatic.get("domain_id")
                chat_id_val = tatic.get("chat_id")
                cursor.execute(query_tactic, (
                    tatic.get("name"),
                    tatic.get("description"),
                    tatic.get("time"),
                    int(chat_id_val) if chat_id_val else None,
                    strategy_id,
                    int(domain_id_val) if domain_id_val else None
                ))

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": "Strategy updated!"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400


# @strategies_bp.route('/strategies/time/<int:strategy_id>', methods=['GET'])
# def get_strategy_by_id(strategy_id):
#     strategy = Strategies.query.get(strategy_id)
#     if strategy:
#         return jsonify({"id": strategy.id, "name": strategy.name, "tatics": [t.as_dict() for t in strategy.tatics]}), 200
#     return jsonify({"error": "Strategy not found"}), 404


# @strategies_bp.route('/strategies/full_tatics_time', methods=['GET'])
# def get_full_tatics_time():
#     ids = request.args.getlist('ids')
    
#     if not ids:
#         return jsonify({"error": "No IDs provided"}), 400

#     try:
#         # converte todos os ids para inteiros
#         ids = list(map(int, ids))
#     except ValueError:
#         return jsonify({"error": "IDs must be integers"}), 400

#     strategies = Strategies.query.filter(Strategies.id.in_(ids)).all()

#     if not strategies:
#         return jsonify({"error": "No strategies found"}), 404

#     full_tactics_time = 0

#     for strategy in strategies:
#         for tactic in strategy.tatics:  # Acesso via atributo, não via dicionário
#             full_tactics_time += getattr(tactic, "time", 0)  # ou tactic.time se tiver certeza que tem esse atributo

#     return jsonify({"full_tactics_time": round(full_tactics_time, 2)}), 200

# @strategies_bp.route('/strategies/remove/<int:strategy_id>', methods=['DELETE'])
# def remove_strategy(strategy_id):
#     strategy = Strategies.query.get(strategy_id)
#     if not strategy:
#         return jsonify({"error": "Strategy not found"}), 404
    
#     db.session.delete(strategy)
#     db.session.commit()
#     return jsonify({"success": "Strategy removed!"}), 200

# ---------------------------------------------------------
# 1. Rota: GET STRATEGY BY ID (comentada no seu código original como /strategies/time/<id>)
# mas o nome da função era get_strategy_by_id. Mantive a lógica.
# ---------------------------------------------------------
@strategies_bp.route('/strategies/time/<int:strategy_id>', methods=['GET'])
def get_strategy_by_id(strategy_id):
    # Reutiliza a lógica de strategy_by_id pois retornam a mesma estrutura
    return strategy_by_id(strategy_id)


# ---------------------------------------------------------
# 2. Rota: GET FULL TATICS TIME
# ---------------------------------------------------------
@strategies_bp.route('/strategies/full_tatics_time', methods=['GET'])
def get_full_tatics_time():
    ids = request.args.getlist('ids')
    
    if not ids:
        return jsonify({"error": "No IDs provided"}), 400

    try:
        # converte todos os ids para inteiros
        ids = list(map(int, ids))
    except ValueError:
        return jsonify({"error": "IDs must be integers"}), 400

    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Monta a query com IN (%s, %s, ...)
        placeholders = ', '.join(['%s'] * len(ids))
        query = f"SELECT SUM(time) as total_time FROM tactics WHERE strategy_id IN ({placeholders})"
        
        cursor.execute(query, tuple(ids))
        result = cursor.fetchone()

        total_time = result['total_time'] if result and result['total_time'] is not None else 0

        cursor.close()
        conn.close()

        return jsonify({"full_tactics_time": round(float(total_time), 2)}), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------
# 3. Rota: REMOVE STRATEGY
# ---------------------------------------------------------
@strategies_bp.route('/strategies/remove/<int:strategy_id>', methods=['DELETE'])
def remove_strategy(strategy_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # 1. Verifica se existe primeiro (para manter o comportamento de 404)
        check_query = "SELECT 1 FROM strategies WHERE id = %s"
        cursor.execute(check_query, (strategy_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Strategy not found"}), 404

        # 2. Deleta
        # Cascade no banco cuida de deletar tactics
        delete_query = "DELETE FROM strategies WHERE id = %s"
        cursor.execute(delete_query, (strategy_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"success": "Strategy removed!"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400    

# @strategies_bp.route('/chat')
# def chat():
#     # return 'oi'
#     return render_template('chat.html')

# @strategies_bp.route('/chat/show', methods=['GET'])
# def show_chats():
#     all_chats = Message.query.all()
#     return jsonify([{"id": c.id, "messages": c.messages} for c in all_chats]), 200

# # Criar uma nova mensagem privada
# @strategies_bp.route('/private_chat/send', methods=['POST'])
# def send_private_message():
#     data = request.json
#     msg = PrivateMessage(
#         sender_id=data['sender_id'],
#         receiver_id=data['receiver_id'],
#         content=data['content']
#     )
#     db.session.add(msg)
#     db.session.commit()
#     return jsonify(msg.as_dict()), 201

# ============================
# 💬 ROTA DE CHAT (Renderização)
# ============================
@strategies_bp.route('/chat')
def chat():
    # Apenas renderiza o HTML, sem banco de dados necessário aqui
    return render_template('chat.html')


# ============================
# 📜 MOSTRAR CHATS (GET)
# ============================
@strategies_bp.route('/chat/show', methods=['GET'])
def show_chats():
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id FROM message;")
        chats = cursor.fetchall()
        
        for chat in chats:
            # Reconstruct 'messages' list from general_message
            cursor.execute("SELECT username, content FROM general_message WHERE message_id = %s ORDER BY timestamp ASC;", (chat['id'],))
            chat['messages'] = cursor.fetchall()

        cursor.close()
        conn.close()

        # O retorno é direto, pois a estrutura já está pronta
        return jsonify(chats), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


# ============================
# 📩 ENVIAR MENSAGEM PRIVADA (POST)
# ============================
@strategies_bp.route('/private_chat/send', methods=['POST'])
def send_private_message():
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.json
    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # ATENÇÃO: Esta rota usa 'receiver_id' que não existe no novo schema.
        # O novo schema exige 'message_id' (chat/sala) para mensagens privadas.
        # Portanto, esta rota está quebrada se o client não mandar message_id.
        # Vou tentar inserir se os dados estiverem presentes, mas caso contrário falhará.
        # Como o objetivo é "adaptar", e a tabela mudou, esta rota antiga perde sentido sem update do client.
        
        # Tentativa de manter compatibilidade se possível, mas provavelmente falhará
        # pois não temos message_id aqui.
        
        return jsonify({"error": "Endpoint deprecated or incompatible with new schema (missing message_id)"}), 400

    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400
    

# @strategies_bp.route('/strategies/ids_to_names', methods=['GET'])
# def ids_to_names():
#     ids = request.args.getlist('ids')
    
#     if not ids:
#         return jsonify({"error": "No IDs provided"}), 400

#     try:
#         # converte todos os ids para inteiros
#         ids = list(map(int, ids))
#     except ValueError:
#         return jsonify({"error": "IDs must be integers"}), 400

#     strategies = Strategies.query.filter(Strategies.id.in_(ids)).all()

#     if not strategies:
#         return jsonify({"error": "No strategies found"}), 404

#     result = [ {
#         "name": strategy.name, 
#         "tatics": [tatic.as_dict() for tatic in strategy.tatics] } 
#         for strategy in strategies ]

#     return jsonify(result), 200


# @strategies_bp.route('/chat/<int:strategy_id>', methods=['GET'])
# def get_strategy_chat(strategy_id):
#     chat = Message.query.get(strategy_id)
#     if chat:
#         return jsonify(chat.as_dict()), 200
#     return jsonify({"error": "Chat not found"}), 404


# @strategies_bp.route('/chat/create', methods=['POST'])
# def create_chat():    
#     new_chat = Message()
#     db.session.add(new_chat)
#     db.session.commit()
#     return jsonify({"success": "Chat created!", "id": new_chat.id}), 200

# ============================
# 🔍 BUSCAR NOMES POR IDS (GET)
# ============================
@strategies_bp.route('/strategies/ids_to_names', methods=['GET'])
def ids_to_names():
    ids = request.args.getlist('ids')
    
    if not ids:
        return jsonify({"error": "No IDs provided"}), 400

    try:
        # converte todos os ids para inteiros
        ids = list(map(int, ids))
    except ValueError:
        return jsonify({"error": "IDs must be integers"}), 400

    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Cria os placeholders (%s, %s, ...) dinamicamente
        placeholders = ', '.join(['%s'] * len(ids))
        
        cursor.execute(f"SELECT id, name, score FROM strategies WHERE id IN ({placeholders})", tuple(ids))
        strategies = cursor.fetchall()

        if not strategies:
             cursor.close()
             conn.close()
             return jsonify({"error": "No strategies found"}), 404

        for s in strategies:
            cursor.execute("SELECT id, name, description, time, chat_id, domain_id FROM tactics WHERE strategy_id = %s", (s['id'],))
            s['tatics'] = cursor.fetchall()

        # Monta o resultado no formato exato que você pediu.
        result = [
            {
                "id": s['id'],
                "name": s['name'],
                "tatics": s['tatics'],
                "score": s['score']
            } 
            for s in strategies
        ]

        cursor.close()
        conn.close()

        return jsonify(result), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


# ============================
# 💬 PEGAR CHAT POR ID (GET)
# ============================
@strategies_bp.route('/chat/<int:strategy_id>', methods=['GET'])
def get_strategy_chat(strategy_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Seleciona o chat
        query = "SELECT id FROM message WHERE id = %s"
        cursor.execute(query, (strategy_id,))
        chat = cursor.fetchone()

        if chat:
            # Seleciona mensagens gerais
            cursor.execute("SELECT username, content FROM general_message WHERE message_id = %s ORDER BY timestamp ASC", (strategy_id,))
            chat['messages'] = cursor.fetchall()

            cursor.close()
            conn.close()
            return jsonify(chat), 200
        
        cursor.close()
        conn.close()
        return jsonify({"error": "Chat not found"}), 404

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


# ============================
# 🆕 CRIAR NOVO CHAT (POST)
# ============================
@strategies_bp.route('/chat/create', methods=['POST'])
def create_chat():    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Inserimos com DEFAULT VALUES pois só tem ID
        query = "INSERT INTO message DEFAULT VALUES RETURNING id;"
        
        cursor.execute(query)
        new_row = cursor.fetchone()
        conn.commit()

        cursor.close()
        conn.close()

        # Retorna sucesso e o ID novo
        return jsonify({"success": "Chat created!", "id": new_row['id']}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400
    


# # --- NOVOS ENDPOINTS ---

# @strategies_bp.route('/chat/<int:chat_id>/general_messages', methods=['GET'])
# def get_general_messages(chat_id):
#     """Retorna apenas as mensagens do chat geral."""
#     chat = Message.query.get(chat_id)
#     if chat:
#         return jsonify(chat.as_dict()), 200 
#     return jsonify({"error": "Chat not found"}), 404

# @strategies_bp.route('/chat/<int:chat_id>/private_messages/<string:myUsername>/<string:target_username>', methods=['GET'])
# def get_private_messages(chat_id, myUsername, target_username):
#     """Retorna o histórico de mensagens entre dois usuários específicos."""
#     chat = Message.query.get(chat_id)
#     if not chat:
#         return jsonify({"error": "Chat not found"}), 404
        
#     messages = PrivateMessage.query.filter(
#         PrivateMessage.message_id == chat_id,
#         or_(
#             (PrivateMessage.username == myUsername) & (PrivateMessage.target_username == target_username),
#             (PrivateMessage.username == target_username) & (PrivateMessage.target_username == myUsername)
#         )
#     ).order_by(PrivateMessage.timestamp.asc()).all()
    
#     return jsonify([msg.as_dict() for msg in messages]), 200

# @strategies_bp.route('/chat/<int:chat_id>/add_message', methods=['POST'])
# def add_message(chat_id):
#     """Adiciona uma mensagem ao chat geral. Retorna apenas a mensagem adicionada."""
#     chat = Message.query.get(chat_id)
#     if not chat:
#         return jsonify({"error": "Chat not found"}), 404
    
#     data = request.json
#     new_message = {"username": data.get('username'), "content": data.get('content')}
#     chat.messages.append(new_message)
#     db.session.commit()
#     return jsonify(new_message), 201 # 201 Created

# @strategies_bp.route('/chat/<int:chat_id>/add_priv_message', methods=['POST'])
# def add_priv_message(chat_id):
#     """Adiciona uma mensagem privada. Retorna a mensagem criada."""
#     chat = Message.query.get(chat_id)
#     if not chat:
#         return jsonify({"error": "Chat not found"}), 404

#     data = request.json
#     msg = PrivateMessage(
#         sender_id=data.get('sender_id'),
#         content=data.get('content'),
#         username=data.get('username'), # Adicionando username
#         target_username=data.get('target_username') # Adicionando target_username
#     )
#     chat.messages_privates.append(msg)
#     # Não precisa de db.session.add(msg) por causa do cascade
#     db.session.commit()
    
#     return jsonify(msg.as_dict()), 201

# ==========================================
# 1. GET GENERAL MESSAGES (Chat Geral)
# ==========================================
@strategies_bp.route('/chat/<int:chat_id>/general_messages', methods=['GET'])
def get_general_messages(chat_id):
    """Retorna apenas as mensagens do chat geral."""
    # Reutiliza get_strategy_chat que retorna {id:..., messages:[...]}
    return get_strategy_chat(chat_id)


# ==========================================
# 2. GET PRIVATE MESSAGES (Histórico entre 2 usuários)
# ==========================================
@strategies_bp.route('/chat/<int:chat_id>/private_messages/<string:myUsername>/<string:target_username>', methods=['GET'])
def get_private_messages(chat_id, myUsername, target_username):
    """Retorna o histórico de mensagens entre dois usuários específicos."""
    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # 1. Verifica se o Chat existe (para manter o padrão do código original)
        check_query = "SELECT 1 FROM message WHERE id = %s"
        cursor.execute(check_query, (chat_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Chat not found"}), 404

        # 2. Busca as mensagens privadas com filtro OR
        # Tradução do SQLAlchemy:
        # (user == A AND target == B) OR (user == B AND target == A)
        query = """
            SELECT * FROM private_message
            WHERE message_id = %s
            AND (
                (username = %s AND target_username = %s) 
                OR 
                (username = %s AND target_username = %s)
            )
            ORDER BY timestamp ASC;
        """
        
        cursor.execute(query, (chat_id, myUsername, target_username, target_username, myUsername))
        messages = cursor.fetchall()

        cursor.close()
        conn.close()

        # O RealDictCursor retorna dicts, então não precisa de list comprehension com .as_dict()
        return jsonify(messages), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


# ==========================================
# 3. ADD MESSAGE (Ao Chat Geral - Normalizado)
# ==========================================
@strategies_bp.route('/chat/<int:chat_id>/add_message', methods=['POST'])
def add_message(chat_id):
    """Adiciona uma mensagem ao chat geral. Retorna apenas a mensagem adicionada."""
    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Verifica se o chat existe
        check_query = "SELECT 1 FROM message WHERE id = %s"
        cursor.execute(check_query, (chat_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Chat not found"}), 404

        data = request.json
        username = data.get('username')
        content = data.get('content')
        
        insert_query = """
            INSERT INTO general_message (username, content, message_id)
            VALUES (%s, %s, %s);
        """
        
        cursor.execute(insert_query, (username, content, chat_id))
        conn.commit()

        cursor.close()
        conn.close()

        # Retorna o objeto simples, como o original fazia
        return jsonify({"username": username, "content": content}), 201

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400


# ==========================================
# 4. ADD PRIVATE MESSAGE (Tabela Relacional)
# ==========================================
@strategies_bp.route('/chat/<int:chat_id>/add_priv_message', methods=['POST'])
def add_priv_message(chat_id):
    """Adiciona uma mensagem privada. Retorna a mensagem criada."""
    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Verifica se o chat pai existe
        check_query = "SELECT 1 FROM message WHERE id = %s"
        cursor.execute(check_query, (chat_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Chat not found"}), 404

        data = request.json
        
        # Insert na tabela private_message
        # Usamos message_id como a chave estrangeira para o chat pai
        insert_query = """
            INSERT INTO private_message (sender_id, content, username, target_username, message_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, sender_id, content, username, target_username, timestamp, message_id;
        """
        
        cursor.execute(insert_query, (
            data.get('sender_id'),
            data.get('content'),
            data.get('username'),
            data.get('target_username'),
            chat_id
        ))
        
        new_msg = cursor.fetchone()
        conn.commit()

        cursor.close()
        conn.close()
        
        return jsonify(new_msg), 201

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400
