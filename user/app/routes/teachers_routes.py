from flask import Blueprint, request, jsonify, current_app
from db import create_connection

teachers_bp = Blueprint("teachers_bp", __name__)

# ============================
# 👨‍🏫 ENDPOINTS PARA PROFESSORES
# ============================

@teachers_bp.route("/teachers/create", methods=["GET", "POST"])
def create_teacher():
    if request.method != "POST":
        return jsonify({"error": "Método não permitido"}), 405

    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        if not request.is_json:
             return jsonify({"error": "Content-Type must be application/json"}), 415

        # Migração automática das colunas de TCLE
        for col_def in [
            "tcle_data_aceite TIMESTAMP",
            "tcle_ip VARCHAR(60)",
            "tcle_user_agent TEXT",
            "tcle_versao VARCHAR(20)",
        ]:
            try:
                cursor.execute(f"ALTER TABLE teacher ADD COLUMN IF NOT EXISTS {col_def};")
                conn.commit()
            except Exception:
                conn.rollback()

        name = request.json["name"]
        age = request.json["age"]
        type_user = "teacher"
        email = request.json["email"]
        username = request.json["username"]
        password = request.json["password"]
        tcle_data_aceite = request.json.get("tcle_data_aceite")
        tcle_ip = request.json.get("tcle_ip")
        tcle_user_agent = request.json.get("tcle_user_agent")
        tcle_versao = request.json.get("tcle_versao", "1.0")

        query = """
            INSERT INTO teacher (name, age, type, email, username, password_hash,
                                 tcle_data_aceite, tcle_ip, tcle_user_agent, tcle_versao)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (name, age, type_user, email, username, password,
                               tcle_data_aceite, tcle_ip, tcle_user_agent, tcle_versao))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Professor criado com sucesso!"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route("/teachers", methods=["GET"])
def get_teachers():
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # TRUQUE: Usamos 'AS' para renomear as colunas para o nome exato da chave do JSON.
        # teacher_id vira 'id', password_hash vira 'password'.
        query = """
            SELECT 
                teacher_id AS id, 
                name, 
                age, 
                type, 
                username, 
                password_hash AS password 
            FROM teacher;
        """
        cursor.execute(query)
        rows = cursor.fetchall() # Já retorna [{"id": 1, "name": "...", ...}]

        cursor.close()
        conn.close()

        # Como rows já é a lista de dicts no formato certo, retornamos direto!
        return jsonify(rows), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route("/teachers/<int:teacher_id>", methods=["GET"])
def get_teacher(teacher_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        query = """
            SELECT 
                teacher_id AS id, 
                name, 
                age, 
                type, 
                username 
            FROM teacher 
            WHERE teacher_id = %s;
        """
        cursor.execute(query, (teacher_id,))
        row = cursor.fetchone() # Retorna {"id": 1, "name": "...", ...} ou None

        cursor.close()
        conn.close()

        if row:
            return jsonify(row), 200
        else:
            return jsonify({"error": "Professor não encontrado"}), 404

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route("/teachers/<int:teacher_id>", methods=["PUT"])
def update_teacher(teacher_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Verifica existência e pega dados atuais
        check_query = "SELECT name, age FROM teacher WHERE teacher_id = %s"
        cursor.execute(check_query, (teacher_id,))
        current_data = cursor.fetchone() # Retorna dict ex: {"name": "João", "age": 30}

        if not current_data:
            cursor.close()
            conn.close()
            return jsonify({"error": "Professor não encontrado"}), 404

        data = request.get_json()
        
        # Acessa o dict retornado pelo banco pelas chaves
        new_name = data.get("name", current_data['name'])
        new_age = data.get("age", current_data['age'])

        update_query = "UPDATE teacher SET name = %s, age = %s WHERE teacher_id = %s;"
        cursor.execute(update_query, (new_name, new_age, teacher_id))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Professor atualizado!", "teacher": data}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route("/teachers/<int:teacher_id>", methods=["DELETE"])
def delete_teacher(teacher_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        # Apenas verifica se existe
        check_query = "SELECT 1 FROM teacher WHERE teacher_id = %s"
        cursor.execute(check_query, (teacher_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Professor não encontrado"}), 404

        delete_query = "DELETE FROM teacher WHERE teacher_id = %s;"
        cursor.execute(delete_query, (teacher_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Professor deletado!"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route('/teachers/ids_to_usernames', methods=['GET'])
def ids_to_names():
    ids = request.args.getlist('ids')
    
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()
    
    try:
        ids = list(map(int, ids))
        
        if not ids:
             cursor.close()
             conn.close()
             result = { "usernames": [], "ids_with_usernames": [{"username": 'ND', "id": 'ND', 'type': 'estudante'}] }
             return jsonify(result), 200

        placeholders = ', '.join(['%s'] * len(ids))
        # Alias 'id' aqui facilita o acesso no loop
        query = f"SELECT teacher_id AS id, username FROM teacher WHERE teacher_id IN ({placeholders})"
        
        cursor.execute(query, tuple(ids))
        rows = cursor.fetchall() # Lista de dicts

        usernames = []
        ids_with_usernames = []

        for row in rows:
            # Acessamos por chave agora
            usernames.append(row['username'])
            ids_with_usernames.append({
                "username": row['username'], 
                "id": row['id'], 
                'type': 'professor' 
            })

        result = { 
            "usernames": usernames,
            "ids_with_usernames": ids_with_usernames 
        }

        cursor.close()
        conn.close()
        return jsonify(result), 200
    
    except ValueError:
        if conn: conn.close()
        result = { "usernames": [], "ids_with_usernames": [{"username": 'ND', "id": 'ND', 'type': 'estudante'}] }
        return jsonify(result), 200
    
    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400


@teachers_bp.route('/teachers/all_teachers_usernames', methods=['GET'])
def all_teachers_usernames():
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        query = "SELECT username FROM teacher;"
        cursor.execute(query)
        rows = cursor.fetchall() # Lista de dicts: [{'username': 'a'}, {'username': 'b'}]

        # List comprehension acessando a chave 'username'
        usernames = [row['username'] for row in rows]
        
        cursor.close()
        conn.close()
    
        return jsonify({"usernames": usernames}), 200

    except Exception as e:
        if conn: conn.close()
        return jsonify({"error": str(e)}), 400

# from flask import Blueprint, request, jsonify, render_template, redirect, url_for
# from ..models import Teacher
# from .. import db

# teachers_bp = Blueprint("teachers_bp", __name__)
# # ============================
# # 👨‍🏫 ENDPOINTS PARA PROFESSORES
# # ============================
# @teachers_bp.route("/teachers/create", methods=["GET", "POST"])
# def create_teacher():

#     if(request.method == "POST"):
#         name = request.json["name"]
#         age = request.json["age"]
#         type = "teacher"
#         email = request.json["email"]
#         username = request.json["username"]
#         password = request.json["password"]

#         teacher = Teacher(name=name, age=age, type=type, email=email, username=username, password_hash=password)
#         db.session.add(teacher)
#         db.session.commit()
#         return jsonify({"message": "Professor criado com sucesso!"}), 200  # Retorna uma mensagem de sucesso
    
#     return jsonify({"error": "Método não permitido"}), 405  # Retorna um erro se o método não for POST
    

# @teachers_bp.route("/teachers", methods=["GET"])
# def get_teachers():
#     teachers = Teacher.query.all()
#     return jsonify([{"id": t.id, "name": t.name, "age": t.age, "type": t.type, "username": t.username, "password": t.password_hash} for t in teachers])

# @teachers_bp.route("/teachers/<int:teacher_id>", methods=["GET"])
# def get_teacher(teacher_id):
#     teacher = Teacher.query.get(teacher_id)
#     if teacher:
#         return jsonify({"id": teacher.id, "name": teacher.name, "age": teacher.age, "type": teacher.type, "username": teacher.username})
#     return jsonify({"error": "Professor não encontrado"}), 404

# @teachers_bp.route("/teachers/<int:teacher_id>", methods=["PUT"])
# def update_teacher(teacher_id):
#     teacher = Teacher.query.get(teacher_id)
#     if teacher:
#         data = request.get_json()
#         teacher.name = data.get("name", teacher.name)
#         teacher.age = data.get("age", teacher.age)
#         db.session.commit()
#         return jsonify({"message": "Professor atualizado!", "teacher": data})
#     return jsonify({"error": "Professor não encontrado"}), 404

# @teachers_bp.route("/teachers/<int:teacher_id>", methods=["DELETE"])
# def delete_teacher(teacher_id):
#     teacher = Teacher.query.get(teacher_id)
#     if teacher:
#         db.session.delete(teacher)
#         db.session.commit()
#         return jsonify({"message": "Professor deletado!"})
#     return jsonify({"error": "Professor não encontrado"}), 404


# @teachers_bp.route('/teachers/ids_to_usernames', methods=['GET'])
# def ids_to_names():
#     ids = request.args.getlist('ids')
#     # if not teachers:
#     #     return jsonify({"error": "No teachers found"}), 404
    
#     try:
#         # converte todos os ids para inteiros
#         ids = list(map(int, ids))
#         teachers = Teacher.query.filter(Teacher.id.in_(ids)).all()
        
#         result = { "usernames": [teacher.username for teacher in teachers],
#                 "ids_with_usernames": [{"username": teacher.username, "id": teacher.id, 'type': 'professor'} for teacher in teachers] }

#         return jsonify(result), 200
    
#     except ValueError:
#         result = { "usernames": [],
#                "ids_with_usernames": [{"username": 'ND', "id": 'ND', 'type': 'estudante'}] }
#         return jsonify(result), 200




# @teachers_bp.route('/teachers/all_teachers_usernames', methods=['GET'])
# def all_teachers_usernames():
#     teachers = Teacher.query.all()
    
#     # if not teachers:
#     #     return jsonify({"error": "No teachers found"}), 404

#     usernames = [teacher.username for teacher in teachers]
    
#     return jsonify({"usernames": usernames}), 200