from flask import Blueprint, render_template, request, redirect, url_for, make_response, current_app, jsonify
from requests.exceptions import RequestException
from .auth import token_required
import requests
import jwt

from .auth import verificar_cookie
from .services_routs import USER_URL

login_bp = Blueprint("login", __name__)

@login_bp.route("/")
def home_page():
    print("Entrou na home")
    current_user = verificar_cookie()

    if current_user:
        # Se o usuário estiver autenticado, redireciona para a página de inicial
        return render_template("dashboard.html", current_user=current_user)
    
    return render_template("start.html")

@login_bp.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")

        try:
            response = requests.post(f"{USER_URL}/login", json={"username": username, "password": password})
            if response.status_code == 200:
                token = response.json().get("token")

                try:
                    payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
                    target = url_for('session.list_sessions') if payload.get('type') == 'student' else url_for('login.home_page')
                except Exception:
                    target = url_for('login.home_page')

                resp = make_response(redirect(target))
                resp.set_cookie('access_token', token, httponly=True, max_age=86400)  # 24 horas
                return resp
            else:
                return render_template("login.html", error="Login failed.")
        except RequestException as e:
            return render_template("login.html", error="User service unavailable.")
    
    return render_template("login.html")

@login_bp.route('/logout')
def logout():
    # Criar uma resposta redirecionando para a tela de login
    resp = make_response(redirect(url_for('login.home_page')))
    
    # Remover o cookie do token
    resp.set_cookie('access_token', '', expires=0)
    
    return resp

@login_bp.route('/perfil')
@token_required
def perfil(current_user=None):
    user_id = current_user['id']
    if current_user["type"] == "student":
        url = f"{USER_URL}/students/{user_id}"
    else:
        url = f"{USER_URL}/teachers/{user_id}"

    response = requests.get(url)
    user = response.json()
    return render_template('perfil.html', user=user, current_user=current_user)


@login_bp.route('/perfil/update', methods=['POST'])
@token_required
def update_perfil(current_user=None):
    user_id = current_user['id']
    data = request.get_json() or {}
    try:
        if current_user["type"] == "student":
            resp = requests.put(f"{USER_URL}/students/{user_id}", json=data)
        else:
            resp = requests.put(f"{USER_URL}/teachers/{user_id}", json=data)
        try:
            return jsonify(resp.json()), resp.status_code
        except Exception:
            return resp.text, resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503