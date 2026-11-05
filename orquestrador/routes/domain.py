from flask import Blueprint, render_template, request, redirect, url_for, make_response, flash, jsonify, Response
from requests.exceptions import RequestException
from .auth import token_required
import requests
import json
from flask import stream_with_context

from .auth import verificar_cookie
from .services_routs import DOMAIN_URL

domain_bp = Blueprint("domain", __name__)

@domain_bp.route("/domains/create", methods=["GET", "POST"])  
@token_required
def create_domain(current_user=None):
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        youtube_links = request.form.getlist("videos_youtube")
        files = request.files.getlist("pdfs")
        videos = request.files.getlist("videos_uploaded")  # apenas um vídeo

        # Captura exercícios do formulário
        exercises = []
        index = 0
        while True:
            question_key = f"exercises[{index}][question]"
            correct_key = f"exercises[{index}][correct]"

            if question_key not in request.form:
                break

            question = request.form.get(question_key)
            correct = request.form.get(correct_key)

            options = []
            option_index = 0
            while True:
                option_key = f"exercises[{index}][options][{option_index}]"
                if option_key not in request.form:
                    break
                options.append(request.form.get(option_key))
                option_index += 1

            exercises.append({
                "question": question,
                "options": options,
                "correct": correct
            })

            index += 1

        # Dados enviados como form-data
        data = {
            'name': name,
            'description': description,
            'youtube_link': [youtube_link for youtube_link in youtube_links],
            'exercises': json.dumps(exercises)
        }

        # Arquivos a serem enviados para API
        files_payload = [
            ('pdfs', (file.filename, file.stream, file.content_type))
            for file in files
        ]

        for vid in videos:
            if vid.filename:
                files_payload.append(('video', (vid.filename, vid.stream, vid.content_type)))



        # return f"{data} - {files_payload}"
        # Requisição para o microserviço
        response = requests.post(f"{DOMAIN_URL}/domains/create", data=data, files=files_payload)

        if response.ok:
            return render_template('/domain/success.html')
        else:
            flash(f"Falha ao criar domínio. {response.status_code} - {response.text}")
            return redirect(url_for('domain.create_domain'))

    return render_template('/domain/create_domain.html')


@domain_bp.route("/domains", methods=["GET"])
@token_required
def list_domains(current_user=None):
    try:
        # Faz uma requisição GET para o microserviço de domínio
        response = requests.get(f"{DOMAIN_URL}/domains")
        response.raise_for_status()  # Levanta um erro se a resposta não for 200 OK
        # return f"{response.json()}"
        domains = response.json()
    except RequestException as e:
        flash("Failed to fetch domains.")
        domains = []

    
    # return f"{domains}"

    return render_template("/domain/list_domains.html", domains=domains)
    # return jsonify(domains), 200  # Retorna a lista de domínios em formato JSON

@domain_bp.route("/domains/delete/<int:domain_id>", methods=["POST"])
def delete_domain(current_user=None, domain_id=None):
    try:
        # Faz uma requisição DELETE para o microserviço de domínio
        response = requests.delete(f"{DOMAIN_URL}/domains/delete/{domain_id}")
        response.raise_for_status()  # Levanta um erro se a resposta não for 200 OK
        return redirect('/domains')  # Redireciona para a lista de domínios após a exclusão
    except RequestException as e:
        flash("Failed to delete domain.")
        return jsonify({"error": "Failed to delete domain"}), 500

@domain_bp.route("/domains/<int:domain_id>", methods=["GET"])
@token_required
def get_domain(current_user=None, domain_id=None):
    try:
        # Faz uma requisição GET para o microserviço de domínio
        response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}")
        response.raise_for_status()  # Levanta um erro se a resposta não for 200 OK
        # return f"{response.json()}"
        domain = response.json()
    except RequestException as e:
        flash("Failed to fetch domain.")
        domain = None

    
    # return f"{domain}"

    return render_template("/domain/domain_detail.html", domain=domain)
    # return jsonify(domain), 200  # Retorna os detalhes do domínio em formato JSON


@domain_bp.route("/domains/<int:domain_id>/edit", methods=["GET", "POST"])
@token_required
def edit_domain(current_user=None, domain_id=None):
    if request.method == "GET":
        try:
            response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}")
            response.raise_for_status()
            domain = response.json()
        except RequestException:
            flash("Falha ao carregar domínio.")
            return redirect(url_for('domain.list_domains'))
        return render_template('/domain/edit_domain.html', domain=domain)

    # POST: coleta dados e encaminha ao serviço domain
    name = request.form.get("name")
    description = request.form.get("description")
    youtube_links = request.form.getlist("videos_youtube")
    files = request.files.getlist("pdfs")
    videos = request.files.getlist("videos_uploaded")

    exercises = []
    index = 0
    while True:
        if f"exercises[{index}][question]" not in request.form:
            break
        question = request.form.get(f"exercises[{index}][question]")
        correct = request.form.get(f"exercises[{index}][correct]")
        options = []
        opt_i = 0
        while f"exercises[{index}][options][{opt_i}]" in request.form:
            options.append(request.form.get(f"exercises[{index}][options][{opt_i}]"))
            opt_i += 1
        exercises.append({"question": question, "options": options, "correct": correct})
        index += 1

    data = {
        'name': name,
        'description': description,
        'youtube_link': youtube_links,
        'delete_pdf_ids': request.form.getlist("delete_pdf_ids"),
        'delete_youtube_ids': request.form.getlist("delete_youtube_ids"),
        'delete_video_ids': request.form.getlist("delete_video_ids"),
        'delete_exercise_ids': request.form.getlist("delete_exercise_ids"),
        'exercises': json.dumps(exercises),
    }

    files_payload = [('pdfs', (f.filename, f.stream, f.content_type)) for f in files if f.filename]
    for vid in videos:
        if vid.filename:
            files_payload.append(('video', (vid.filename, vid.stream, vid.content_type)))

    response = requests.post(f"{DOMAIN_URL}/domains/{domain_id}/update", data=data, files=files_payload if files_payload else None)

    if response.ok:
        flash("Domínio atualizado com sucesso!")
        return redirect(url_for('domain.list_domains'))
    else:
        flash(f"Falha ao atualizar domínio. {response.status_code} - {response.text}")
        return redirect(url_for('domain.edit_domain', domain_id=domain_id))


@domain_bp.route("/domains/domains_json", methods=["GET"])
def get_domains_json():
    try:
        response = requests.get(f"{DOMAIN_URL}/domains")
        response.raise_for_status()
        return jsonify(response.json()), 200
    except RequestException as e:
        return jsonify({"error": "Domain service unavailable", "details": str(e)}), 503


@domain_bp.route("/domains/<int:domain_id>/pdfs", methods=["GET"])
@token_required
def get_domain_pdfs(domain_id, current_user=None):
    try:
        response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}")
        response.raise_for_status()
        return jsonify(response.json().get('pdfs', [])), 200
    except RequestException:
        return jsonify([]), 200


@domain_bp.route('/pdfs/<int:pdf_id>', methods=['GET'])
@token_required
def proxy_pdf_download(current_user=None, pdf_id=None):
    try:
        # Requisição para o domínio
        response = requests.get(f"{DOMAIN_URL}/pdfs/{pdf_id}", stream=True)
        response.raise_for_status()

        # Pega o nome original do arquivo do header
        content_disposition = response.headers.get('Content-Disposition')
        filename = "download.pdf"
        if content_disposition and 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[1].strip('"')

        # Retorna o conteúdo como download para o usuário
        return Response(
            response.iter_content(chunk_size=8192),
            content_type=response.headers['Content-Type'],
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except RequestException:
        return "Failed to download file", 500
    

@domain_bp.route("/domains/<int:domain_id>/exercises", methods=["GET"])
@token_required
def get_exercises(domain_id, current_user=None):
    response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}/exercises")
    return jsonify(response.json()), response.status_code


@domain_bp.route('/domains/<int:domain_id>/videos', methods=["GET"])
@token_required
def get_videos(domain_id, current_user=None):
    response = requests.get(f"{DOMAIN_URL}/domains/{domain_id}/videos")
    return jsonify(response.json()), response.status_code


@domain_bp.route("/video/uploaded/<int:video_id>", methods=["GET"])
def get_uploaded_video(video_id):
    headers = {"Authorization": request.headers.get("Authorization")}
    api_response = requests.get(f"{DOMAIN_URL}/video/uploaded/{video_id}", headers=headers, stream=True)

    if api_response.status_code != 200:
        return Response("Erro ao buscar vídeo da API", status=api_response.status_code)

    return Response(
        stream_with_context(api_response.iter_content(chunk_size=8192)),
        content_type=api_response.headers.get('Content-Type', 'video/mp4')
    )

