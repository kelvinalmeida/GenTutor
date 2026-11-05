from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
import requests
import io
from .auth import token_required
from .services_routs import USER_URL, DOMAIN_URL

student_bp = Blueprint("student", __name__)

@student_bp.route('/tcle/pdf', methods=['GET'])
def download_tcle_pdf():
    try:
        resp = requests.get(f"{DOMAIN_URL}/uploads/tcle_pdf", timeout=15)
        if resp.status_code == 200:
            return send_file(
                io.BytesIO(resp.content),
                mimetype='application/pdf',
                download_name='TCLE_SEP-Agentic.pdf'
            )
        return "PDF não disponível", 404
    except Exception as e:
        return str(e), 500


@student_bp.route('/students/create', methods=['POST', 'GET'])
def create_students():
    if request.method == 'POST':
        if request.form.get('tcle_aceito') != 'sim':
            return render_template("./user/create_student.html", error_tcle="Você deve aceitar o TCLE para realizar o cadastro.")

        # Get the form data
        name = request.form["name"]
        age = request.form["age"]
        course = request.form["course"]
        type = "student"
        email = request.form["email"]
        username = request.form["username"]
        password = request.form["password"]
        pref_content_type = request.form.get("pref_content_type")
        pref_communication = request.form.get("pref_communication")
        pref_receive_email = True if request.form.get("pref_receive_email") == 'true' else False

        student = {
            "name": name,
            "age": age,
            "course": course,
            "type": type,
            "email": email,
            "username": username,
            "password": password,
            "pref_content_type": pref_content_type,
            "pref_communication": pref_communication,
            "pref_receive_email": pref_receive_email,
            "tcle_data_aceite": datetime.now(BRT).isoformat(),
            "tcle_ip": request.remote_addr,
            "tcle_user_agent": request.headers.get("User-Agent", ""),
            "tcle_versao": "1.0",
        }
        
        try:
            all_students_usernames = requests.get(f"{USER_URL}/students/all_students_usernames").json()
            all_teachers_usernames = requests.get(f"{USER_URL}/teachers/all_teachers_usernames").json()
            
            # return f"{all_students_usernames} {all_teachers_usernames}"
            if username in all_students_usernames["usernames"] or username in all_teachers_usernames["usernames"]:
                return render_template("./user/create_student.html", error="Username already exists")
            
            response = requests.post(f"{USER_URL}/students/create", json=student)

            if response.status_code == 201:
                # json_response = response.json()
                # return jsonify(json_response), 200
                return render_template("./user/success.html")

            else:
                return jsonify({"error": "Failed to create student", "details": response.text}), response.status_code
        except RequestException as e:
            return jsonify({"error": "User service unavailable", "details": str(e)}), 503
    
    return render_template("./user/create_student.html")
    

@student_bp.route('/students', methods=['GET'])
@token_required
def get_students(current_user=None):
    try:
        response = requests.get(f"{USER_URL}/students")
        students = response.json()  # pega o JSON
        # return f"{students}"
        return render_template("./user/list_students.html", students=students, current_user=current_user)
    except RequestException as e:
        return jsonify({"error": "User service unavailable", "details": str(e)}), 503


@student_bp.route('/students/<int:student_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def get_student_by_id(student_id, current_user=None):
    try:
        url = f"{USER_URL}/students/{student_id}"
        if request.method == 'GET':
            response = requests.get(url)
        elif request.method == 'PUT':
            response = requests.put(url, json=request.get_json())
        elif request.method == 'DELETE':
            response = requests.delete(url)
        return jsonify(response.json()), response.status_code
    except RequestException as e:
        return jsonify({"error": "User service unavailable", "details": str(e)}), 503