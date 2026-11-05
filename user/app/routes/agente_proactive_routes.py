import logging
import os
from flask import Blueprint, request, jsonify
from openai import OpenAI
from config import Config

agente_proactive_bp = Blueprint('agente_proactive_bp', __name__)
logging.basicConfig(level=logging.INFO)


@agente_proactive_bp.route('/agent/proactive_recommendation', methods=['POST'])
def proactive_recommendation():
    """
    Gera recomendação proativa focada no tópico da sessão atual.
    Recebe contexto anonimizado: maestria, domínio, exercícios (sem gabarito), preferência.
    Nenhum dado pessoal (nome, username, email) é enviado ao LLM.
    """
    data = request.get_json() or {}
    session_domain = data.get('session_domain', {})
    session_exercises = data.get('session_exercises', [])
    pref_content_type = data.get('pref_content_type', '')

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    domain_name = session_domain.get('name', '')
    domain_desc = session_domain.get('description', '')

    if domain_name or domain_desc:
        topic_section = (
            f"TÓPICO DA SESSÃO ATUAL:\n"
            f"- Domínio: {domain_name or 'Não especificado'}\n"
            f"- Descrição: {domain_desc[:300] if domain_desc else 'Não informada'}"
        )
    else:
        topic_section = "TÓPICO: Sessão de aprendizado (conteúdo não especificado)."

    if session_exercises:
        ex_lines = "\n".join(
            f"  {i+1}. {q}" for i, q in enumerate(session_exercises[:6])
        )
        exercises_section = f"\nEXERCÍCIOS DA SESSÃO (apenas enunciados, SEM gabarito):\n{ex_lines}"
    else:
        exercises_section = ""

    pref_section = f"\nPREFERÊNCIA DE CONTEÚDO: {pref_content_type}" if pref_content_type else ""

    system_prompt = f"""Você é um tutor educacional que gera mini-conteúdos de aprendizagem durante uma sessão.

REGRAS ABSOLUTAS:
1. NUNCA forneça respostas diretas para exercícios, questões de prova ou avaliações
2. NÃO mencione qual é a alternativa correta de nenhum exercício
3. Use SEMPRE "você" — jamais nomes ou identificações pessoais
4. Escreva em linguagem clara, didática e acessível
5. Máximo 200 palavras"""

    user_prompt = f"""{topic_section}{exercises_section}{pref_section}

Com base no conteúdo desta sessão, gere um MINI-CONTEÚDO EDUCATIVO que ajude o estudante a entender melhor o que está sendo ensinado pelo professor:
- Explique um conceito central do domínio "{domain_name or 'da sessão'}" com suas próprias palavras
- Use um exemplo prático ou analogia do cotidiano para ilustrar
- Conecte a explicação ao tema dos exercícios da sessão, sem revelar respostas
- Termine com uma pergunta reflexiva para estimular o raciocínio do estudante"""

    try:
        client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=350
        )
        recommendation = (response.choices[0].message.content or "").strip()
        return jsonify({"recommendation": recommendation, "type": "proactive"}), 200
    except Exception as e:
        logging.error("Erro na recomendação proativa: %s", str(e))
        return jsonify({"error": str(e)}), 500


@agente_proactive_bp.route('/agent/chat_answer', methods=['POST'])
def chat_answer():
    """
    Responde perguntas do estudante com foco no tópico da sessão atual.
    Contexto anonimizado: maestria, domínio, exercícios (sem gabarito), preferência.
    Jamais responde questões de exercícios diretamente.
    """
    data = request.get_json() or {}
    question = data.get('question', '').strip()
    session_domain = data.get('session_domain', {})
    session_exercises = data.get('session_exercises', [])
    pref_content_type = data.get('pref_content_type', '')

    if not question:
        return jsonify({"error": "question é obrigatória"}), 400

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    domain_name = session_domain.get('name', '')
    domain_desc = session_domain.get('description', '')

    context_parts = []

    if domain_name or domain_desc:
        context_parts.append(
            f"Tópico da sessão: {domain_name}" +
            (f" — {domain_desc[:200]}" if domain_desc else "")
        )

    if session_exercises:
        ex_sample = "; ".join(session_exercises[:4])
        context_parts.append(f"Exercícios da sessão (enunciados apenas): {ex_sample}")

    if pref_content_type:
        context_parts.append(f"Preferência de conteúdo: {pref_content_type}")

    system_prompt = f"""Você é um tutor educacional inteligente acompanhando ESTUDANTE na sessão de "{domain_name or 'aprendizagem'}".
{('Contexto do domínio: ' + domain_desc[:200]) if domain_desc else ''}

REGRAS ABSOLUTAS:
1. NUNCA forneça respostas diretas para exercícios, questões de prova ou avaliações
2. Se ESTUDANTE pedir "a resposta do exercício X", recuse e ofereça orientação pedagógica
3. Explique conceitos do tópico "{domain_name or 'da sessão'}" com analogias, exemplos práticos e linguagem clara
4. Incentive o raciocínio autônomo — faça perguntas que guiem ESTUDANTE à conclusão
5. Use SEMPRE "ESTUDANTE" — jamais nomes ou identificações pessoais
6. Mantenha o foco no tópico desta sessão
7. Seja encorajador, paciente e pedagogicamente responsável
8. Máximo 200 palavras"""

    messages = [{"role": "system", "content": system_prompt}]
    if context_parts:
        messages.append({
            "role": "system",
            "content": "Contexto educacional anonimizado da sessão:\n" + "\n".join(context_parts)
        })
    messages.append({"role": "user", "content": question})

    try:
        client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.4,
            max_tokens=300
        )
        answer = (response.choices[0].message.content or "").strip()
        return jsonify({"answer": answer}), 200
    except Exception as e:
        logging.error("Erro na resposta do chat: %s", str(e))
        return jsonify({"error": str(e)}), 500
