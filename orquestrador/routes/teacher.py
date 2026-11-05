from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
import requests
from .auth import token_required
from .services_routs import USER_URL

teacher_bp = Blueprint("teacher", __name__)

@teacher_bp.route('/teachers/create', methods=['POST', 'GET'])
def create_teacher():
    if request.method == 'POST':
        if request.form.get('tcle_aceito') != 'sim':
            return render_template("./user/create_teacher.html", error_tcle="Você deve aceitar o TCLE para realizar o cadastro.")

        # Get the form data
        name = request.form["name"]
        age = request.form["age"]
        type = "teacher"
        email = request.form["email"]
        username = request.form["username"]
        password = request.form["password"]

        teacher = {
            "name": name,
            "age": age,
            "type": type,
            "email": email,
            "username": username,
            "password": password,
            "tcle_data_aceite": datetime.now(BRT).isoformat(),
            "tcle_ip": request.remote_addr,
            "tcle_user_agent": request.headers.get("User-Agent", ""),
            "tcle_versao": "1.0",
        }
        
        try:
            # Requisições
            students_response = requests.get(f"{USER_URL}/students/all_students_usernames")
            teachers_response = requests.get(f"{USER_URL}/teachers/all_teachers_usernames")

            # return jsonify({"students_status": students_response.json(),
            #     "teachers_status": teachers_response.json()}), 200

            # Verifique se deu certo
            if students_response.status_code != 200 or teachers_response.status_code != 200:
                return jsonify({
                    "error": "Erro ao verificar usernames",
                    "details": {
                        "students_status": students_response.status_code,
                        "teachers_status": teachers_response.status_code
                    }
                }), 503

            all_students_usernames = students_response.json()
            all_teachers_usernames = teachers_response.json()

            # Verifique se as chaves existem
            students_usernames = all_students_usernames.get("usernames", [])
            teachers_usernames = all_teachers_usernames.get("usernames", [])

            # return jsonify({"students_usernames": students_usernames,
            #     "teachers_usernames": teachers_usernames, 'username': username}), 200

            if username in students_usernames or username in teachers_usernames:
                return render_template("./user/create_teacher.html", error="Username already exists")


            response = requests.post(f"{USER_URL}/teachers/create", json=teacher)
            if response.status_code == 200:
                # json_response = response.json()
                # return jsonify(json_response), 200
                return render_template("./user/success.html")
            else:
                return jsonify({"error": "Failed to create teacher", "details": response.text}), response.status_code
        except RequestException as e:
            return jsonify({"error": "User service unavailable", "details": str(e)}), 503
    
    return render_template("./user/create_teacher.html")

@teacher_bp.route('/teachers', methods=['GET'])
@token_required
def get_teachers(current_user=None):
    try:
        response = requests.get(f"{USER_URL}/teachers")
        teachers = response.json()  # pega o JSON
        return render_template("./user/list_teachers.html", teachers=teachers, current_user=current_user)
    except RequestException as e:
        return jsonify({"error": "User service unavailable", "details": str(e)}), 503


@teacher_bp.route('/teachers/<int:teacher_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_teacher(teacher_id, current_user=None):
    try:
        url = f"{USER_URL}/teachers/{teacher_id}"
        if request.method == 'GET':
            response = requests.get(url)
        elif request.method == 'PUT':
            response = requests.put(url, json=request.get_json())
        elif request.method == 'DELETE':
            response = requests.delete(url)
        return (response.text, response.status_code, response.headers.items())
    except RequestException as e:
        return jsonify({"error": "User service unavailable", "details": str(e)}), 503