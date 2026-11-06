import logging
import json
from flask import Blueprint, request, jsonify
from config import Config
from openai import OpenAI

logging.basicConfig(level=logging.INFO)

agente_plan_bp = Blueprint('agente_plan_bp', __name__)

TACTIC_TYPE_DESCRIPTIONS = """TIPOS DE TÁTICAS E O QUE CADA UMA FAZ:
- Reuso: Apresenta recursos didáticos (PDFs, vídeos, exercícios) por um tempo determinado.
- Debate Síncrono: Chat em tempo real entre alunos e professor.
- Envio de Informação: Envia materiais por e-mail para os alunos.
- Mudança de Estratégia: Troca a estratégia didática atual por outra.
- Regra: Executa ações condicionalmente com base em uma condição verificada."""


def _build_groq_client():
    return OpenAI(
        api_key=Config.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )


@agente_plan_bp.route('/agent/plan_session_tactics', methods=['POST'])
def plan_session_tactics():
    """
    Gera um plano completo de sessão: ordem das táticas + objetivo geral + justificativas.
    Usado tanto para o planejamento inicial quanto para replanejamento com táticas restantes.

    Retorna: { tactic_sequence: [2, 0, 1], overall_goal: "...", tactic_reasons: {"0": "...", ...} }
    """
    data = request.get_json() or {}
    student_profile = data.get('student_profile', '')
    class_profile = data.get('class_profile', '')
    exercise_scores = data.get('exercise_scores', '')
    all_tactics = data.get('all_tactics', [])  # [{"index": i, "name": ..., "description": ...}]
    chat_messages = data.get('chat_messages', [])
    student_history = data.get('student_history', '')
    student_mastery = data.get('student_mastery', '')
    is_replan = bool(data.get('is_replan', False))

    if not all_tactics:
        return jsonify({"error": "all_tactics é obrigatório e não pode estar vazio"}), 400

    if not Config.GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

    tactics_text = "\n".join(
        f"- Índice {t['index']}: {t['name']} | {str(t.get('description', ''))[:120]}"
        for t in all_tactics
    )
    valid_indices = [t['index'] for t in all_tactics]
    chat_text = "\n".join(f"- {m}" for m in chat_messages) if chat_messages else "Sem mensagens recentes."
    history_text = student_history if student_history else "Primeira sessão — sem histórico anterior."
    mastery_text = student_mastery if student_mastery else "Sem dados de maestria (primeira sessão)."
    replan_note = "\nATENÇÃO: Este é um REPLANEJAMENTO. O aluno teve dificuldades. Ajuste a ordem para reforçar pontos fracos.\n" if is_replan else ""

    try:
        prompt = f"""
Você é um tutor pedagógico especializado em aprendizagem adaptativa.
Sua tarefa é criar um PLANO COMPLETO de sessão de aprendizagem para este aluno,
ordenando TODAS as táticas disponíveis na melhor sequência pedagógica.
{replan_note}
{TACTIC_TYPE_DESCRIPTIONS}

PERFIL INDIVIDUAL DO ALUNO:
{student_profile}

PERFIL DA TURMA:
{class_profile}

DESEMPENHO DO ALUNO NOS EXERCÍCIOS:
{exercise_scores}

HISTÓRICO DE SESSÕES ANTERIORES:
{history_text}

MAESTRIA POR CONCEITO (menor % = maior necessidade de reforço):
{mastery_text}

ÚLTIMAS MENSAGENS DO ALUNO NO CHAT:
{chat_text}

TÁTICAS DISPONÍVEIS (devem aparecer exatamente uma vez no plano):
{tactics_text}

Responda APENAS em JSON neste formato exato:
{{
  "tactic_sequence": [<lista ordenada com TODOS os índices: {valid_indices}>],
  "overall_goal": "<objetivo pedagógico claro para esta sessão em 1-2 frases>",
  "tactic_reasons": {{
    "<índice como string>": "<justificativa breve de por que esta tática está nesta posição>"
  }}
}}

REGRAS OBRIGATÓRIAS:
- tactic_sequence deve conter EXATAMENTE os índices {valid_indices}, cada um UMA única vez.
- A ordem deve maximizar o aprendizado considerando o perfil individual do aluno.
- Priorize abordar conceitos com menor maestria primeiro.
- overall_goal deve ser claro, específico e motivador para o aluno.
"""

        logging.info("Prompt de planejamento enviado à IA (is_replan=%s)", is_replan)

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

        # Valida e corrige tactic_sequence
        raw_seq = parsed.get('tactic_sequence', [])
        seq = []
        seen = set()
        for i in raw_seq:
            try:
                idx = int(i)
                if idx in valid_indices and idx not in seen:
                    seq.append(idx)
                    seen.add(idx)
            except (ValueError, TypeError):
                pass
        # Adiciona índices ausentes ao final
        for idx in valid_indices:
            if idx not in seen:
                seq.append(idx)

        logging.info("Plano gerado: sequence=%s goal=%s", seq, parsed.get("overall_goal", ""))

        return jsonify({
            "tactic_sequence": seq,
            "overall_goal": parsed.get("overall_goal", ""),
            "tactic_reasons": parsed.get("tactic_reasons", {})
        }), 200

    except Exception as e:
        logging.error("Erro em plan_session_tactics: %s", str(e))
        return jsonify({"error": str(e)}), 500
