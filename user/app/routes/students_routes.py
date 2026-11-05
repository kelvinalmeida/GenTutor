from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
# from ..models import Student
from .. import db
from db import create_connection

student_bp = Blueprint("student_bp", __name__)

@student_bp.route("/students/create", methods=["GET", "POST"])
def create_student():

    # Tenta criar a conexão
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    
    # FIX 1: Verifica se a conexão falhou (é None) antes de continuar
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503

    cursor = conn.cursor()

    if request.method == "POST":
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
                col_name = col_def.split()[0]
                try:
                    cursor.execute(f"ALTER TABLE student ADD COLUMN IF NOT EXISTS {col_def};")
                    conn.commit()
                except Exception:
                    conn.rollback()

            name = request.json.get("name")
            age = request.json.get("age")
            course = request.json.get("course")
            type = "student"
            email = request.json.get("email")
            username = request.json.get("username")
            password = request.json.get("password")
            pref_content_type = request.json.get("pref_content_type")
            pref_communication = request.json.get("pref_communication")
            pref_receive_email = request.json.get("pref_receive_email")
            tcle_data_aceite = request.json.get("tcle_data_aceite")
            tcle_ip = request.json.get("tcle_ip")
            tcle_user_agent = request.json.get("tcle_user_agent")
            tcle_versao = request.json.get("tcle_versao", "1.0")

            add_student_query = """
                INSERT INTO student (
                    name, age, course, type, email, username, password_hash,
                    pref_content_type, pref_communication, pref_receive_email,
                    tcle_data_aceite, tcle_ip, tcle_user_agent, tcle_versao
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """

            cursor.execute(add_student_query, (
                name, age, course, type, email, username, password,
                pref_content_type, pref_communication, pref_receive_email,
                tcle_data_aceite, tcle_ip, tcle_user_agent, tcle_versao
            ))
            
            conn.commit()

            # FIX 2: Fechar cursor e conexão no sucesso
            cursor.close()
            conn.close()

            return jsonify({"message": "Aluno criado com sucesso!"}), 201
        
        except Exception as e:
            # FIX 3: Rollback seguro e fechamento de recursos
            if conn:
                conn.rollback()
                cursor.close()
                conn.close()
            return jsonify({"error": str(e)}), 400

    # Se for GET ou outro método, fecha a conexão que foi aberta no início
    if conn:
        conn.close()

    return jsonify({"error": "Método não permitido"}), 405

@student_bp.route("/students", methods=["GET"])
def get_students(): 
    # Tenta criar a conexão
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    
    # FIX 1: Verifica se a conexão falhou (é None) antes de continuar
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        get_students_query = "SELECT student_id id, name, age, course, type, username, password_hash password FROM student;"
        cursor.execute(get_students_query)
        rows = cursor.fetchall()

        students = []
        # for row in rows:
        #     student = Student(id=row[0], name=row[1], age=row[2], course=row[3], type=row[4], username=row[5], password_hash=row[6])
        #     students.append(student)

        # FECHAR ANTES DO RETURN
        cursor.close()
        conn.close()

        # Se você tiver configurado o cursor para retornar dicionários (RealDictCursor), isso funciona direto.
        # Se não, rows será uma lista de tuplas e o JSON ficará como arrays [[id, name...], ...].
        return jsonify(rows), 200
    except Exception as e:
        # FIX 3: Rollback seguro e fechamento de recursos
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400

    # return jsonify([{"id": s.id, "name": s.name, "age": s.age, "course": s.course, "type": s.type, "username": s.username, "password": s.password_hash} for s in students])

@student_bp.route("/students/<int:student_id>/contact", methods=["GET"])
def get_student_contact(student_id):
    """Retorna nome e email do aluno para uso interno (notificações ao professor)."""
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, email FROM student WHERE student_id = %s;", (student_id,))
        row = cursor.fetchone()
        if row:
            return jsonify({"name": row["name"], "email": row["email"]}), 200
        return jsonify({"error": "Aluno não encontrado"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        cursor.close()
        conn.close()


@student_bp.route("/students/<int:student_id>", methods=["GET"])
def get_student_by_id(student_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        get_student_query = """SELECT student_id id, name, age, course, type, username,
                                     email, pref_content_type, pref_communication, pref_receive_email
                              FROM student WHERE student_id = %s;"""
        cursor.execute(get_student_query, (student_id,))
        row = cursor.fetchone()

        if row:
            return jsonify(row), 200
        else:
            return jsonify({"error": "Aluno não encontrado"}), 404

    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400

    # student = Student.query.get(student_id)
    # if student:
    #     return jsonify({"id": student.id, "name": student.name, "age": student.age, "course": student.course, "username": student.username, "type": student.type})
    # return jsonify({"error": "Aluno não encontrado"}), 404

@student_bp.route("/students/<int:student_id>", methods=["PUT"])
def update_student(student_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()
    try:
        name = request.json.get("name")
        age = request.json.get("age")
        course = request.json.get("course")
        email = request.json.get("email")
        pref_content_type = request.json.get("pref_content_type")
        pref_communication = request.json.get("pref_communication")
        pref_receive_email = request.json.get("pref_receive_email")

        update_student_query = """UPDATE student
                                  SET name = %s, age = %s, course = %s,
                                      email = %s, pref_content_type = %s,
                                      pref_communication = %s, pref_receive_email = %s
                                  WHERE student_id = %s;"""

        cursor.execute(update_student_query, (name, age, course, email,
                                              pref_content_type, pref_communication,
                                              pref_receive_email, student_id))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Aluno atualizado!"}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400
    
    # student = Student.query.get(student_id)
    # if student:
    #     data = request.get_json()
    #     student.name = data.get("name", student.name)
    #     student.age = data.get("age", student.age)
    #     student.course = data.get("course", student.course)
    #     db.session.commit()
    #     return jsonify({"message": "Aluno atualizado!", "student": data})
    # return jsonify({"error": "Aluno não encontrado"}), 404

@student_bp.route("/students/<int:student_id>", methods=["DELETE"])
def delete_student(student_id):
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    cursor = conn.cursor()
    try:
        delete_student_query = "DELETE FROM student WHERE student_id = %s;"
        cursor.execute(delete_student_query, (student_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "Aluno deletado!"}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
            conn.close()
        return jsonify({"error": str(e)}), 400
    # student = Student.query.get(student_id)
    # if student:
    #     db.session.delete(student)
    #     db.session.commit()
    #     return jsonify({"message": "Aluno deletado!"})
    # return jsonify({"error": "Aluno não encontrado"}), 404


@student_bp.route("/students/<int:student_id>/preferences", methods=["GET"])
def get_student_preferences(student_id):
    """Retorna dados brutos de preferências do aluno sem chamar LLM."""
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT name, course, age, pref_content_type, pref_communication, pref_receive_email
            FROM student WHERE student_id = %s
        """, (student_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Aluno não encontrado"}), 404
        return jsonify(dict(row)), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cursor.close()
        conn.close()


@student_bp.route('/students/batch_preferences', methods=['POST'])
def batch_preferences():
    """Retorna dados brutos de preferências para uma lista de alunos sem chamar LLM."""
    data = request.get_json() or {}
    student_ids = data.get('student_ids', [])
    if not student_ids:
        return jsonify({"students": []}), 200
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    cursor = conn.cursor()
    try:
        clean_ids = [int(x) for x in student_ids]
        cursor.execute("""
            SELECT name, pref_content_type, pref_communication, pref_receive_email
            FROM student WHERE student_id = ANY(%s)
        """, (clean_ids,))
        rows = cursor.fetchall()
        return jsonify({"students": [dict(r) for r in rows]}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cursor.close()
        conn.close()


@student_bp.route('/students/ids_to_usernames', methods=['GET'])
def ids_to_names():
    # 1. Pegar os IDs da URL
    ids = request.args.getlist('ids')
    
    if not ids:
        result = { 
            "usernames": [],
            "ids_with_usernames": [{"username": '', "id": '', 'type': 'estudante'}] 
        }
        return jsonify(result), 200

    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        ids = list(map(int, ids))

        placeholders = ', '.join(['%s'] * len(ids))
        
        # O Select pede 'student_id' e 'username'
        query = f"SELECT student_id, username FROM student WHERE student_id IN ({placeholders})"

        cursor.execute(query, tuple(ids))
        rows = cursor.fetchall()

        usernames = []
        ids_with_usernames = []

        for row in rows:
            # CORREÇÃO AQUI: Acessar pelo NOME da coluna (chave do dicionário)
            # row é algo como: {'student_id': 4, 'username': 'maria'}
            s_id = row['student_id']
            s_username = row['username']

            usernames.append(s_username)
            ids_with_usernames.append({
                "username": s_username, 
                "id": s_id, 
                'type': 'estudante'
            })

        result = {
            "usernames": usernames,
            "ids_with_usernames": ids_with_usernames if ids_with_usernames else [{"username": '', "id": '', 'type': 'estudante'}]
        }

        cursor.close()
        conn.close()
        
        return jsonify(result), 200

    except Exception as e:
        if conn:
            conn.close()
        # Dica: print(e) no terminal ajuda a ver o erro real (KeyError)
        return jsonify({"error": str(e)}), 400

    except ValueError:
        # Caso a conversão map(int, ids) falhe
        if conn: conn.close()
        result = { "usernames": [], "ids_with_usernames": [{"username": '', "id": '', 'type': 'estudante'}] }
        return jsonify(result), 200

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 400

# @student_bp.route('/students/ids_to_usernames', methods=['GET'])
# def ids_to_names():
#     ids = request.args.getlist('ids')

#     try:
#         # converte todos os ids para inteiros
#         ids = list(map(int, ids))
#         students = Student.query.filter(Student.id.in_(ids)).all()

#         result = { "usernames": [student.username for student in students],
#                 "ids_with_usernames": [{"username": student.username, "id": student.id, 'type': 'estudante'} for student in students] }

#         return jsonify(result), 200
    
#     except ValueError:
#         result = { "usernames": [],
#                "ids_with_usernames": [{"username": '', "id": '', 'type': 'estudante'}] }
#         return jsonify(result), 200

@student_bp.route('/students/all_students_usernames', methods=['GET'])
def all_students_usernames():
    conn = create_connection(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 503
    
    cursor = conn.cursor()

    try:
        query = "SELECT username FROM student;"
        cursor.execute(query)
        rows = cursor.fetchall()

        usernames = [row['username'] for row in rows]

        cursor.close()
        conn.close()

        return jsonify({"usernames": usernames}), 200

    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"error": str(e)}), 400

# @student_bp.route('/students/all_students_usernames', methods=['GET'])
# def all_students_usernames():
#     students = Student.query.all()
    
#     # if not students:
#     #     return jsonify({"error": "No students found"}), 404

#     usernames = [student.username for student in students]
#     # ids_with_usernames = [{"username": student.username, "id": student.id, 'type': 'estudante'} for student in students]

#     return jsonify({"usernames": usernames}), 200