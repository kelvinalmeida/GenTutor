import logging
import os
import json
from flask import Blueprint, request, jsonify, current_app
# from google import genai
from config import Config
from openai import OpenAI

# Tenta importar a conexão do banco de dados
try:
    from db import create_connection
except ImportError:
    from ...db import create_connection

agente_control_bp = Blueprint('agente_control_bp', __name__)


def _normalize_options(options_raw):
    """
    Normaliza opções para lista de textos.
    Aceita list, dict ou string JSON.
    """
    options = options_raw
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except Exception:
            return []

    if isinstance(options, dict):
        # Ordena por chave quando possível para preservar sequência
        try:
            return [str(v) for _, v in sorted(options.items(), key=lambda kv: int(kv[0]))]
        except Exception:
            return [str(v) for v in options.values()]

    if isinstance(options, list):
        return [str(v) for v in options]

    return []


def _resolve_option_text(option_value, options):
    """
    Converte resposta codificada (ex: 0/1/2) para texto da alternativa.
    Suporta índice 0-based e 1-based.
    """
    if not options:
        return option_value

    try:
        idx = int(option_value)
    except Exception:
        return option_value

    # 0-based
    if 0 <= idx < len(options):
        return options[idx]

    # 1-based
    if 1 <= idx <= len(options):
        return options[idx - 1]

    return option_value

# ... (Mantenha suas outras rotas existentes: create_session, etc.) ...

# ==============================================================================
# AGENTE DE MEMÓRIA (CONTROL): RESUMO GERAL DA SESSÃO (Foco na Turma/Estratégia)
# ==============================================================================
@agente_control_bp.route('/sessions/<int:session_id>/agent_summary', methods=['GET'])
def agent_session_summary(session_id):
    """
    Agente Control: Analisa os dados macro da sessão.
    Foco: Desempenho geral, adesão às atividades extras e status do plano de aula.
    Não analisa alunos individualmente.
    """
    conn = None
    try:
        # 1. Conexão
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        
        if not conn:
            return jsonify({"error": "Falha na conexão com o banco de dados"}), 500

        with conn.cursor() as cur:
            # A. Dados da Sessão
            cur.execute("""
                SELECT status, start_time, current_tactic_index, rating_average, rating_count
                FROM session 
                WHERE id = %s
            """, (session_id,))
            session_info = cur.fetchone()

            if not session_info:
                return jsonify({"error": "Sessão não encontrada"}), 404

            # B. Total de Estratégias no Plano
            cur.execute("""
                SELECT COUNT(*) as total 
                FROM session_strategies 
                WHERE session_id = %s
            """, (session_id,))
            total_strategies = cur.fetchone()['total']

            # C. Dados das respostas verificadas da sessão
            cur.execute("""
                SELECT answers, score
                FROM verified_answers 
                WHERE session_id = %s
            """, (session_id,))
            verified_rows = cur.fetchall()

            # D. Notas Extras (Lista de floats)
            cur.execute("""
                SELECT extra_notes 
                FROM extra_notes 
                WHERE session_id = %s
            """, (session_id,))
            extra_rows = cur.fetchall()
            # Ex: [9.5, 8.0]
            extra_scores = [
                float(row['extra_notes'])
                for row in extra_rows
                if row.get('extra_notes') is not None
            ]

        # 2. Estatísticas Gerais (Cálculos Python)
        submission_scores = []
        total_answered_questions = 0
        total_correct_answers = 0

        for row in verified_rows:
            raw_score = row.get('score') if isinstance(row, dict) else None
            if raw_score is not None:
                try:
                    submission_scores.append(float(raw_score))
                except (TypeError, ValueError):
                    pass

            answers = row.get('answers') if isinstance(row, dict) else []
            if isinstance(answers, str):
                try:
                    answers = json.loads(answers)
                except Exception:
                    answers = []

            if not isinstance(answers, list):
                continue

            for ans in answers:
                if not isinstance(ans, dict):
                    continue
                total_answered_questions += 1
                if bool(ans.get('correct')) is True:
                    total_correct_answers += 1

        avg_submission_score = (
            sum(submission_scores) / len(submission_scores)
            if submission_scores else 0
        )
        correctness_rate = (
            (total_correct_answers / total_answered_questions) * 100
            if total_answered_questions > 0 else 0
        )

        total_extras = len(extra_scores)
        avg_extras = sum(extra_scores) / total_extras if total_extras > 0 else 0

        # 3. Engenharia de Prompt (Foco no Coletivo)
        # Passamos as listas de notas para ele detectar padrões (ex: turma homogênea vs heterogênea)
        prompt = f"""
        Atue como o 'Agente de Memória' de uma plataforma de ensino.
        Analise o estado geral desta Sessão de Ensino (ID {session_id}) para orientar o Orquestrador.
        Não cite alunos. Foque na eficácia das estratégias e no desempenho da turma como um todo.

        DADOS DA SESSÃO:
        - Status: {session_info['status']}
        - Progresso do Plano: {total_strategies} estratégias vinculadas.
        - Avaliação Média da Turma: {session_info.get('rating_average', 0.0):.1f} estrelas ({session_info.get('rating_count', 0)} votos).
        
        DESEMPENHO NOS EXERCÍCIOS OBRIGATÓRIOS:
        - Total de questões respondidas: {total_answered_questions}
        - Total de acertos: {total_correct_answers}
        - Taxa de acerto: {correctness_rate:.1f}%
        - Média de score por submissão: {avg_submission_score:.1f} / 100
        - Scores por submissão: {submission_scores}
        
        DESEMPENHO NAS ATIVIDADES EXTRAS (BÔNUS):
        - Quantidade de entregas: {total_extras}
        - Média Geral: {avg_extras:.1f}
        - Notas: {extra_scores}

        OBJETIVO:
        Gere um resumo narrativo curto (2-3 frases) respondendo:
        1. O conteúdo obrigatório está sendo bem assimilado pela maioria?
        2. Existe interesse/adesão ao conteúdo extra?
        3. A sessão parece fluir bem ou está estagnada (poucas respostas)?
        """

        if not Config.GROQ_API_KEY:
            return jsonify({"error": "GROQ_API_KEY não configurada"}), 500

        # 4. Chamada LLM (Groq)
        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        
        # 2. Chamada LLM (Sem response_format JSON)
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você é um assistente pedagógico conciso."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2 
            # response_format removido para permitir texto livre
        )

        content_text = (response.choices[0].message.content or "").strip()

        # 4. Chamada ao Gemini
        # if not Config.GEMINI_API_KEY:
        #      return jsonify({"error": "GEMINI_API_KEY não configurada"}), 500

        # client = genai.Client(api_key=Config.GEMINI_API_KEY)
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash-lite-preview-09-2025", 
        #     contents=prompt
        # )

        # 5. Retorno
        return jsonify({
            "session_id": session_id,
            "status": session_info['status'],
            "summary": content_text,
            "metrics": {
                "submission_score_avg": round(avg_submission_score, 2),
                "correctness_rate": round(correctness_rate, 2),
                "answered_questions": total_answered_questions,
                "correct_answers": total_correct_answers,
                "extra_avg": round(avg_extras, 2),
                "participation_count": len(submission_scores) + total_extras
            }
        }), 200

    except Exception as e:
        logging.error(f"Erro no Agente Control Summary: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@agente_control_bp.route('/students/<string:student_id>/grades_history', methods=['GET'])
def get_student_grades_history(student_id):
    """
    Retorna o histórico completo de notas de um aluno específico (pelo ID),
    agrupado por Session ID.
    """
    conn = None
    try:
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        
        if not conn:
            return jsonify({"error": "Falha na conexão com o banco"}), 500

        with conn.cursor() as cur:
            # Estrutura: { "session_id": { "notes": [], "extra_notes": [] } }
            history_map = {}

            # ---------------------------------------------------------
            # 1. Buscar Notas de Exercícios (Verified Answers)
            # ---------------------------------------------------------
            # Filtramos pelo student_id (muito mais seguro que nome)
            cur.execute("""
                SELECT session_id, score 
                FROM verified_answers 
                WHERE student_id = %s
            """, (student_id,))
            
            answers = cur.fetchall()
            for row in answers:
                # Tratamento seguro (Dict vs Tupla)
                sess_id = row['session_id'] if isinstance(row, dict) else row[0]
                val = row['score'] if isinstance(row, dict) else row[1]
                
                # O ID da sessão vira a chave (convertido para string para o JSON)
                sess_key = str(sess_id)
                
                if sess_key not in history_map:
                    history_map[sess_key] = {"notes": [], "extra_notes": []}
                
                history_map[sess_key]["notes"].append(val)

            # ---------------------------------------------------------
            # 2. Buscar Notas Extras (Extra Notes)
            # ---------------------------------------------------------
            # Filtramos pelo ID (ajustando a query para student_id)
            cur.execute("""
                SELECT session_id, extra_notes 
                FROM extra_notes 
                WHERE student_id = %s
            """, (int(student_id) if student_id.isdigit() else 0,))
            
            extras = cur.fetchall()
            for row in extras:
                # Tratamento seguro (Dict vs Tupla)
                sess_id = row['session_id'] if isinstance(row, dict) else row[0]
                # Nota: no seu banco a coluna de valor chama-se 'extra_notes' também
                val = row['extra_notes'] if isinstance(row, dict) else row[1]
                
                sess_key = str(sess_id)
                
                if sess_key not in history_map:
                    history_map[sess_key] = {"notes": [], "extra_notes": []}
                
                history_map[sess_key]["extra_notes"].append(val)

            # ---------------------------------------------------------
            # 3. Buscar Avaliações do Aluno (Ratings)
            # ---------------------------------------------------------
            cur.execute("""
                SELECT session_id, rating
                FROM session_ratings
                WHERE student_id = %s
            """, (student_id,))

            ratings = cur.fetchall()
            for row in ratings:
                sess_id = row['session_id'] if isinstance(row, dict) else row[0]
                val = row['rating'] if isinstance(row, dict) else row[1]

                sess_key = str(sess_id)
                if sess_key not in history_map:
                    history_map[sess_key] = {"notes": [], "extra_notes": []}

                history_map[sess_key]["student_rating"] = val

        # 3. LLM Analysis
        analysis_text = "Análise indisponível"
        try:
            if getattr(Config, 'GROQ_API_KEY', None):
                client = OpenAI(
                    api_key=Config.GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )
                prompt = f"""
                Você é um analista de desempenho escolar.
                Analise as notas e identifique tendências (melhora, piora, estagnação) e pontos de atenção.

                Dados brutos (Sessão -> Notas):
                {history_map}

                Responda com um parágrafo conciso.
                """

                resp = client.chat.completions.create(
                    model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
                analysis_text = resp.choices[0].message.content
        except Exception as llm_err:
            logging.warning(f"LLM Error in grades_history: {llm_err}")

        return jsonify({
            "student_performance_summary": analysis_text,
            "raw_history_by_session": history_map
        }), 200

    except Exception as e:
        logging.error(f"Erro ao buscar histórico do aluno {username}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@agente_control_bp.route('/agent/student_session_difficulty_summary', methods=['POST'])
def student_session_difficulty_summary():
    """
    Recebe student_id e session_id, analisa respostas do exercício
    (acertos/erros) e devolve um resumo de até 10 linhas sobre dificuldades.
    """
    data = request.get_json() or {}
    student_id = data.get('student_id')
    session_id = data.get('session_id')

    if student_id is None or session_id is None:
        return jsonify({"error": "student_id e session_id são obrigatórios"}), 400

    conn = None
    try:
        db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
        conn = create_connection(db_url)

        if not conn:
            return jsonify({"error": "Falha na conexão com o banco de dados"}), 500

        with conn.cursor() as cur:
            cur.execute("""
                SELECT student_name, answers, score
                FROM verified_answers
                WHERE student_id = %s AND session_id = %s
                ORDER BY id DESC
                LIMIT 1
            """, (str(student_id), session_id))
            verified = cur.fetchone()

        if not verified:
            return jsonify({"error": "Respostas do aluno não encontradas para esta sessão"}), 404

        raw_answers = verified.get('answers', [])
        if isinstance(raw_answers, str):
            try:
                raw_answers = json.loads(raw_answers)
            except Exception:
                raw_answers = []

        if not isinstance(raw_answers, list) or len(raw_answers) == 0:
            return jsonify({"error": "Estrutura de respostas inválida ou vazia"}), 422

        exercise_map = data.get('exercise_context_by_id', {})
        if not isinstance(exercise_map, dict):
            exercise_map = {}
        exercise_list = list(exercise_map.values())
        try:
            exercise_list.sort(key=lambda ex: int(ex.get("id", 0)))
        except Exception:
            pass

        acertos = []
        erros = []
        linhas_detalhes = []

        for idx, ans in enumerate(raw_answers, start=1):
            if not isinstance(ans, dict):
                continue

            exercise_id = ans.get('exercise_id')
            exercise_data = exercise_map.get(str(exercise_id), {})
            if not exercise_data and exercise_list:
                # fallback para casos em que o exercise_id salvo não corresponde
                # ao id real do domínio (ex: respostas com ids locais 101/102).
                if 0 <= (idx - 1) < len(exercise_list):
                    exercise_data = exercise_list[idx - 1]
            options = _normalize_options(exercise_data.get('options', []))
            options_txt = " | ".join([f"{i}: {opt}" for i, opt in enumerate(options)])

            question_text = (
                ans.get('question')
                or ans.get('question_text')
                or ans.get('enunciado')
                or exercise_data.get('question')
                or exercise_data.get('statement')
                or f"Questão {exercise_id or idx}"
            )
            answer_raw = ans.get('answer', ans.get('user_answer', 'Não informado'))
            correct_raw = (
                ans.get('correct_answer')
                or ans.get('expected_answer')
                or exercise_data.get('correct')
                or 'Não informada'
            )
            resposta_aluno = _resolve_option_text(answer_raw, options)
            resposta_correta = _resolve_option_text(correct_raw, options)
            correto = bool(ans.get('correct', False))

            status = "ACERTOU" if correto else "ERROU"
            linhas_detalhes.append(
                f"- Ex. {exercise_id or idx}: {question_text} | opções: {options_txt} | resposta: {resposta_aluno} | correta: {resposta_correta} | {status}"
            )

            if correto:
                acertos.append(question_text)
            else:
                erros.append(question_text)

        prompt = f"""
        Você é um tutor pedagógico especializado em diagnóstico de aprendizagem.
        Analise as respostas de um aluno na sessão e identifique os assuntos em que ele tem dificuldade.

        DADOS:
        - Aluno: {verified.get('student_name', 'Aluno')}
        - Student ID: {student_id}
        - Sessão: {session_id}
        - Score geral: {verified.get('score', 0)}
        - Total de questões: {len(linhas_detalhes)}
        - Acertos: {len(acertos)}
        - Erros: {len(erros)}

        QUESTÕES E RESPOSTAS:
        {chr(10).join(linhas_detalhes)}

        QUESTÕES ERRADAS (foco de dificuldade):
        {erros if erros else ['Nenhuma questão errada']}

        OBJETIVO:
        Gere um resumo em português com EXATAMENTE 10 linhas curtas explicando:
        1) Quais assuntos aparentam maior dificuldade.
        2) Que padrão de erro aparece nas respostas.
        3) O que priorizar na revisão do aluno.
        4) Sugestões de estudo objetivas.

        Não use markdown, não use JSON, não use título.
        """

        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": "Você gera diagnósticos pedagógicos claros e objetivos."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        summary = (response.choices[0].message.content or "").strip()

        return jsonify({
            "student_id": str(student_id),
            "session_id": int(session_id),
            "score": verified.get('score', 0),
            "total_questions": len(linhas_detalhes),
            "correct_count": len(acertos),
            "wrong_count": len(erros),
            "questions_summary": linhas_detalhes,
            "difficulty_summary": summary
        }), 200

    except Exception as e:
        logging.error(f"Erro em student_session_difficulty_summary: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
