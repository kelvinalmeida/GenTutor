import logging
import json
from flask import Blueprint, request, jsonify
from config import Config
from openai import OpenAI

agente_perso_individual_bp = Blueprint('agente_perso_individual_bp', __name__)


def _build_groq_client():
    return OpenAI(
        api_key=Config.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )


@agente_perso_individual_bp.route('/agent/recommend_youtube_video', methods=['POST'])
def recommend_youtube_video():
    """
    Recebe dificuldade + preferências do aluno e retorna um link de vídeo do YouTube
    sugerido pela IA (Groq) para sanar a principal dificuldade.
    """
    data = request.get_json() or {}
    difficulty_summary = data.get('difficulty_summary', '')
    questions_summary = data.get('questions_summary', [])
    profile_summary = data.get('profile_summary', '')

    if not difficulty_summary and not questions_summary:
        return jsonify({"error": "difficulty_summary ou questions_summary é obrigatório"}), 400

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    try:
        prompt = f"""
        Você é um tutor pedagógico especializado em recomendar vídeo-aulas.
        Analise o diagnóstico abaixo e indique UM vídeo do YouTube para ajudar o aluno.

        PERFIL DO ALUNO:
        {profile_summary}

        RESUMO DE DIFICULDADES:
        {difficulty_summary}

        QUESTÕES (DIAGNÓSTICO):
        {questions_summary}

        Responda APENAS em JSON neste formato:
        {{
          "youtube_url": "https://www.youtube.com/watch?v=...",
          "justification": "explicação curta"
        }}
        """

        client = _build_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Responda apenas JSON válido."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        return jsonify({
            "youtube_url": parsed.get("youtube_url", ""),
            "justification": parsed.get("justification", "")
        }), 200

    except Exception as e:
        logging.error(f"Erro em recommend_youtube_video: {str(e)}")
        return jsonify({"error": str(e)}), 500


@agente_perso_individual_bp.route('/agent/generate_personalized_study_text', methods=['POST'])
def generate_personalized_study_text():
    """
    Gera um texto personalizado (~5 minutos de leitura) para sanar dificuldades do aluno.
    """
    data = request.get_json() or {}
    difficulty_summary = data.get('difficulty_summary', '')
    questions_summary = data.get('questions_summary', [])
    profile_summary = data.get('profile_summary', '')

    if not difficulty_summary and not questions_summary:
        return jsonify({"error": "difficulty_summary ou questions_summary é obrigatório"}), 400

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    try:
        prompt = f"""
        Você é um tutor especializado em personalização individual do aprendizado.
        Com base no diagnóstico, gere um texto didático em português para cerca de 5 minutos de leitura
        (aproximadamente 650 a 800 palavras), adaptado ao perfil do aluno.

        PERFIL DO ALUNO:
        {profile_summary}

        RESUMO DE DIFICULDADES:
        {difficulty_summary}

        QUESTÕES (DIAGNÓSTICO):
        {questions_summary}

        Requisitos do texto:
        - Linguagem simples e objetiva.
        - Explique os conceitos com exemplos práticos.
        - Destaque erros comuns que o aluno está cometendo.
        - Inclua uma mini seção final com 5 passos de revisão.
        - Não use markdown e não use JSON.
        """

        client = _build_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você escreve materiais pedagógicos personalizados com clareza."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )

        study_text = (response.choices[0].message.content or "").strip()

        return jsonify({
            "study_text": study_text
        }), 200

    except Exception as e:
        logging.error(f"Erro em generate_personalized_study_text: {str(e)}")
        return jsonify({"error": str(e)}), 500


@agente_perso_individual_bp.route('/agent/generate_wrong_answers_study_text', methods=['POST'])
def generate_wrong_answers_study_text():
    """
    Gera um texto pedagógico (~5 min de leitura) explicando os conceitos
    das questões erradas pelo aluno, SEM revelar as respostas corretas.
    """
    data = request.get_json() or {}
    wrong_questions = data.get('wrong_questions', [])
    profile_summary = data.get('profile_summary', '')
    student_history = data.get('student_history', '')
    attempt_number = int(data.get('attempt_number', 1))

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    questions_text = "\n".join(f"- {q}" for q in wrong_questions) if wrong_questions else "Tópico geral da sessão de aprendizagem."
    history_text = student_history if student_history else "Primeira sessão — sem histórico anterior."

    is_proactive = (attempt_number == 0)

    if is_proactive:
        approach_instruction = (
            "O aluno está estudando o material e pediu um exemplo adicional. "
            "Crie um exemplo prático e explicativo sobre os tópicos abordados nas questões. "
            "Use situações do cotidiano para ilustrar os conceitos. "
            "Termine com 2-3 dicas de como fixar o conteúdo."
        )
        prompt_intro = (
            "Um aluno está estudando os tópicos listados abaixo e pediu um exemplo adicional para aprofundar o entendimento.\n"
            "Crie um texto educativo em português com cerca de 5 minutos de leitura\n"
            "(aproximadamente 650 a 800 palavras) que explique os conceitos com exemplos práticos."
        )
    elif attempt_number == 1:
        approach_instruction = (
            "Explique os conceitos com exemplos práticos do cotidiano. "
            "Inclua uma mini seção final com 3 dicas de como estudar esses assuntos."
        )
        prompt_intro = (
            f"Um aluno errou as questões listadas abaixo (tentativa número {attempt_number}).\n"
            "Crie um texto educativo em português com cerca de 5 minutos de leitura\n"
            "(aproximadamente 650 a 800 palavras) que explique os conceitos envolvidos."
        )
    elif attempt_number == 2:
        approach_instruction = (
            "O aluno já tentou uma vez e errou novamente. Mude completamente a abordagem: "
            "use analogias criativas e metáforas para explicar os mesmos conceitos de outro ângulo. "
            "Conecte os conceitos à experiência de vida do aluno com uma narrativa ou comparação visual."
        )
        prompt_intro = (
            f"Um aluno errou as questões listadas abaixo (tentativa número {attempt_number}).\n"
            "Crie um texto educativo em português com cerca de 5 minutos de leitura\n"
            "(aproximadamente 650 a 800 palavras) que explique os conceitos envolvidos."
        )
    else:
        approach_instruction = (
            f"O aluno tentou {attempt_number} vezes e ainda não passou. "
            "Adote desmembramento total: explique como se o aluno nunca tivesse visto o assunto, "
            "sem jargões, com um passo a passo numerado para cada conceito, "
            "e termine com um exercício mental guiado (sem ser o exercício do sistema)."
        )
        prompt_intro = (
            f"Um aluno errou as questões listadas abaixo (tentativa número {attempt_number}).\n"
            "Crie um texto educativo em português com cerca de 5 minutos de leitura\n"
            "(aproximadamente 650 a 800 palavras) que explique os conceitos envolvidos."
        )

    try:
        prompt = f"""
Você é um tutor especializado em personalização do aprendizado.
{prompt_intro}

PERFIL DO ALUNO:
{profile_summary}

HISTÓRICO DE SESSÕES ANTERIORES DO ALUNO:
{history_text}

{"TÓPICOS DA SESSÃO (base para o exemplo):" if is_proactive else "QUESTÕES QUE O ALUNO ERROU (apenas o enunciado):"}
{questions_text}

{"ABORDAGEM (exemplo proativo):" if is_proactive else f"ABORDAGEM PARA ESTA TENTATIVA ({attempt_number}ª vez):"}
{approach_instruction}

REGRAS OBRIGATÓRIAS:
- NÃO revele as respostas corretas em nenhum momento.
- NÃO mencione qual era a alternativa certa.
- Escreva em linguagem acessível e motivadora.
- Não use markdown e não use JSON.
"""

        client = _build_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você escreve materiais pedagógicos personalizados. Nunca revele respostas corretas."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )

        study_text = (response.choices[0].message.content or "").strip()

        return jsonify({"study_text": study_text}), 200

    except Exception as e:
        logging.error(f"Erro em generate_wrong_answers_study_text: {str(e)}")
        return jsonify({"error": str(e)}), 500


@agente_perso_individual_bp.route('/agent/extract_exercise_concepts', methods=['POST'])
def extract_exercise_concepts():
    """
    Recebe lista de exercícios com resultado (acertou/errou) e extrai os conceitos
    testados via LLM. Retorna maestria por conceito para rastreamento de longo prazo.
    """
    data = request.get_json() or {}
    exercises = data.get('exercises', [])

    if not exercises:
        return jsonify({"concepts": []}), 200

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    exercises_text = "\n".join(
        f"- {'[CORRETO]' if ex.get('was_correct') else '[ERRADO]'} {ex.get('question', '')}"
        for ex in exercises
    )

    try:
        prompt = f"""Você é um especialista em pedagogia. Analise os exercícios abaixo e identifique os conceitos/tópicos testados.

EXERCÍCIOS (com resultado do aluno):
{exercises_text}

Para cada conceito identificado, some quantas vezes o aluno acertou e errou questões sobre esse conceito.

Responda APENAS em JSON neste formato:
{{
  "concepts": [
    {{"concept": "nome do conceito", "correct_count": <int>, "total_count": <int>}}
  ]
}}

REGRAS:
- Identifique no máximo 5 conceitos distintos
- Use nomes curtos e objetivos (ex: "recursão", "ponteiros", "herança")
- Agrupe questões relacionadas no mesmo conceito
- correct_count deve ser menor ou igual a total_count"""

        client = _build_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você extrai conceitos pedagógicos de exercícios. Responda apenas JSON válido."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        return jsonify({"concepts": parsed.get("concepts", [])}), 200

    except Exception as e:
        logging.error("Erro em extract_exercise_concepts: %s", str(e))
        return jsonify({"error": str(e)}), 500
