import logging
import json
from flask import Blueprint, request, jsonify
from config import Config
from openai import OpenAI


logging.basicConfig(level=logging.INFO)

agente_adaptive_tactic_bp = Blueprint('agente_adaptive_tactic_bp', __name__)

TACTIC_TYPE_DESCRIPTIONS = """TIPOS DE TÁTICAS E O QUE CADA UMA FAZ:
- Reuso: Apresenta um recurso didático (definição, exemplo, exercício) por um tempo determinado.
- Debate Síncrono: Chat em tempo real entre alunos e professor por um período definido.
- Envio de Informação: Envia documentos e materiais por e-mail para uma lista de destinatários.
- Mudança de Estratégia: Troca a estratégia didática atual por outra de uma biblioteca de estratégias.
- Regra: Executa ações condicionalmente com base em uma condição verificada (Se/Então)."""


def _build_groq_client():
    return OpenAI(
        api_key=Config.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )


@agente_adaptive_tactic_bp.route('/agent/decide_adaptive_tactic', methods=['POST'])
def decide_adaptive_tactic():
    """
    Recebe o contexto do aluno e as táticas RESTANTES (já filtradas pelo orquestrador)
    e decide qual delas executar a seguir. Nunca repete táticas já concluídas.
    """
    data = request.get_json() or {}
    student_profile = data.get('student_profile', '')
    class_profile = data.get('class_profile', '')
    exercise_scores = data.get('exercise_scores', '')
    remaining_tactics = data.get('remaining_tactics', [])   # [{"index": i, "name": ..., "description": ...}]
    executed_tactic_indices = data.get('executed_tactic_indices', [])
    chat_messages = data.get('chat_messages', [])
    student_history = data.get('student_history', '')
    student_mastery = data.get('student_mastery', '')

    if not remaining_tactics:
        return jsonify({"error": "remaining_tactics é obrigatório e não pode estar vazio"}), 400

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    remaining_text = "\n".join(
        f"- Índice {t['index']}: {t['name']} | {str(t.get('description', ''))[:120]}"
        for t in remaining_tactics
    )
    done_text = ", ".join(str(i) for i in executed_tactic_indices) if executed_tactic_indices else "nenhuma ainda"
    chat_text = "\n".join(f"- {m}" for m in chat_messages) if chat_messages else "Sem mensagens recentes."
    history_text = student_history if student_history else "Primeira sessão — sem histórico anterior."
    mastery_text = student_mastery if student_mastery else "Sem dados de maestria ainda (primeira sessão)."

    valid_indices = [t['index'] for t in remaining_tactics]

    try:
        prompt = f"""
Você é um tutor pedagógico especializado em aprendizagem adaptativa.
Sua tarefa é escolher a MELHOR próxima tática de ensino para este aluno específico,
considerando seu perfil, desempenho e participação no chat.

{TACTIC_TYPE_DESCRIPTIONS}

PERFIL INDIVIDUAL DO ALUNO:
{student_profile}

PERFIL DA TURMA:
{class_profile}

DESEMPENHO DO ALUNO NOS EXERCÍCIOS:
{exercise_scores}

HISTÓRICO DE SESSÕES ANTERIORES DO ALUNO:
{history_text}

MAESTRIA POR CONCEITO (menor % = maior necessidade de reforço):
{mastery_text}

ÚLTIMAS MENSAGENS DO ALUNO NO CHAT:
{chat_text}

TÁTICAS JÁ REALIZADAS (índices): {done_text}

TÁTICAS DISPONÍVEIS PARA ESCOLHA (apenas estas podem ser selecionadas):
{remaining_text}

Responda APENAS em JSON neste formato exato:
{{
  "next_tactic_index": <número inteiro — DEVE ser um dos índices listados acima: {valid_indices}>,
  "next_tactic_name": "<nome exato da tática escolhida>",
  "reasoning": "<justificativa clara em 1-2 frases de por que esta tática é a mais adequada para este aluno agora>"
}}

REGRAS OBRIGATÓRIAS:
- O índice deve ser EXATAMENTE um dos valores: {valid_indices}
- Considere o perfil do aluno, seu desempenho e suas mensagens no chat para personalizar a escolha.
- Priorize táticas que trabalhem os conceitos com menor maestria.
- Priorize táticas que supram as dificuldades identificadas do aluno.
"""

        logging.info("Prompt enviado à IA: %s", prompt)

        client = _build_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você é especialista em pedagogia adaptativa. Responda apenas JSON válido."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        logging.info("Resposta da IA: %s", parsed)

        return jsonify({
            "next_tactic_index": parsed.get("next_tactic_index"),
            "next_tactic_name": parsed.get("next_tactic_name", ""),
            "reasoning": parsed.get("reasoning", "")
        }), 200

    except Exception as e:
        logging.error("Erro em decide_adaptive_tactic: %s", str(e))
        return jsonify({"error": str(e)}), 500
