import json
import logging
import os
import requests
from datetime import datetime
from openai import OpenAI
from config import Config

logging.basicConfig(level=logging.INFO)

USER_URL = 'http://user:5002'
CONTROL_URL = 'http://agente_sessao:5001'

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_profile",
            "description": "Busca perfil completo do aluno: preferências de conteúdo, estilo de aprendizagem e dados pessoais relevantes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "integer", "description": "ID do aluno"}
                },
                "required": ["student_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_student_mastery",
            "description": "Busca o nível de maestria do aluno por conceito nesta sessão. Valores abaixo de 60% indicam necessidade de reforço.",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "integer"},
                    "session_id": {"type": "integer"}
                },
                "required": ["student_id", "session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_performance",
            "description": "Busca notas, respostas verificadas e progresso atual do aluno na sessão.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "integer"},
                    "student_id": {"type": "integer"}
                },
                "required": ["session_id", "student_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_tactics",
            "description": "Busca as táticas disponíveis na estratégia atual da sessão, com nome, descrição e tempo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "integer"}
                },
                "required": ["session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_past_outcomes",
            "description": "Consulta o histórico de aprendizado: quais táticas funcionaram melhor para este aluno e para alunos com perfil similar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "integer"}
                },
                "required": ["student_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_tactic",
            "description": "AÇÃO: Registra uma intervenção pendente para mudar a tática do aluno na sessão. O orquestrador aplicará esta mudança na próxima interação do aluno.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "integer"},
                    "student_id": {"type": "integer"},
                    "tactic_index": {"type": "integer", "description": "Índice da tática a ser aplicada"},
                    "reason": {"type": "string", "description": "Justificativa pedagógica da mudança"}
                },
                "required": ["session_id", "student_id", "tactic_index", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notify_teacher",
            "description": "AÇÃO: Envia um alerta ao professor sobre a situação pedagógica do aluno na sessão.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "integer"},
                    "student_id": {"type": "integer"},
                    "message": {"type": "string", "description": "Mensagem de alerta para o professor"}
                },
                "required": ["session_id", "student_id", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_outcome",
            "description": "AÇÃO: Registra a decisão tomada no log de aprendizado para que o agente aprenda com ela no futuro.",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "integer"},
                    "session_id": {"type": "integer"},
                    "tactic_chosen": {"type": "string"},
                    "reasoning": {"type": "string"}
                },
                "required": ["student_id", "session_id", "tactic_chosen", "reasoning"]
            }
        }
    }
]

SYSTEM_PROMPT = """Você é o Agente Autônomo de Estratégias Pedagógicas de um sistema tutor inteligente.

Sua missão é monitorar o progresso do aluno em uma sessão de aprendizagem e tomar decisões pedagógicas autônomas.

PROCESSO OBRIGATÓRIO (siga esta ordem):
1. Busque o perfil do aluno (get_student_profile) para entender preferências e estilo de aprendizagem.
2. Busque a maestria atual do aluno nesta sessão (get_student_mastery).
3. Busque o desempenho recente: notas e progresso (get_session_performance).
4. Consulte as táticas disponíveis (get_available_tactics).
5. Consulte o histórico de resultados passados (get_past_outcomes) para aprender com sessões anteriores.
6. Com todos os dados, tome a decisão pedagógica mais adequada:
   - Se o aluno estiver com dificuldade (maestria < 50% ou nota < 60%), mude a tática para uma mais adequada (apply_tactic) E notifique o professor (notify_teacher).
   - Se o aluno estiver indo bem mas a tática atual não for ideal para o perfil dele, sugira uma tática melhor (apply_tactic).
   - Se não houver necessidade de intervenção, apenas notifique se o desempenho for excelente.
7. Sempre registre sua decisão para aprendizado futuro (record_outcome).

PRINCÍPIOS PEDAGÓGICOS:
- Alunos visuais se beneficiam de táticas de Reuso com vídeos ou Debate Síncrono.
- Alunos com maestria < 40% em um conceito precisam urgentemente de Reuso antes de qualquer exercício.
- Nunca force a mesma tática repetida se ela não está funcionando.
- Considere sempre o histórico: o que funcionou antes provavelmente funcionará de novo."""


def _build_groq_client():
    return OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def _tool_get_student_profile(student_id: int) -> dict:
    try:
        r = requests.get(f"{USER_URL}/students/{student_id}", timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                "student_id": student_id,
                "pref_content_type": data.get('pref_content_type', ''),
                "learning_style": data.get('learning_style', ''),
                "name": data.get('name', ''),
                "email": data.get('email', '')
            }
    except Exception as e:
        logging.warning("[AgentCore] get_student_profile falhou: %s", e)
    return {"student_id": student_id, "error": "perfil não encontrado"}


def _tool_get_student_mastery(student_id: int, session_id: int) -> dict:
    try:
        r = requests.get(
            f"{USER_URL}/students/{student_id}/mastery",
            params={"session_id": session_id},
            timeout=8
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logging.warning("[AgentCore] get_student_mastery falhou: %s", e)
    return {"mastery": [], "error": "dados de maestria indisponíveis"}


def _tool_get_session_performance(session_id: int, student_id: int) -> dict:
    try:
        r = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=8)
        if r.status_code == 200:
            session_data = r.json()
            verified = session_data.get('verified_answers', [])
            student_answers = [v for v in verified if str(v.get('student_id')) == str(student_id)]
            scores = []
            for ans in student_answers:
                raw = ans.get('score', 0)
                total = len(ans.get('answers') or []) or 1
                scores.append(round((raw / total) * 100, 1))
            avg_score = round(sum(scores) / len(scores), 1) if scores else None
            return {
                "session_id": session_id,
                "student_id": student_id,
                "current_tactic_index": session_data.get('current_tactic_index', 0),
                "status": session_data.get('status'),
                "scores": scores,
                "avg_score": avg_score,
                "total_answers": len(student_answers)
            }
    except Exception as e:
        logging.warning("[AgentCore] get_session_performance falhou: %s", e)
    return {"session_id": session_id, "student_id": student_id, "error": "dados indisponíveis"}


def _tool_get_available_tactics(session_id: int) -> dict:
    try:
        r = requests.get(f"{CONTROL_URL}/sessions/{session_id}", timeout=8)
        if r.status_code != 200:
            return {"tactics": [], "error": "sessão não encontrada"}
        session_data = r.json()
        strategy_ids = session_data.get('strategies', [])
        if not strategy_ids:
            return {"tactics": []}

        from db import create_connection
        db_url = os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        if not conn:
            return {"tactics": [], "error": "banco indisponível"}
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, description, time
                    FROM tactics
                    WHERE strategy_id = ANY(%s)
                    ORDER BY id
                """, (list(strategy_ids),))
                rows = cur.fetchall()
            return {
                "strategy_ids": strategy_ids,
                "tactics": [
                    {"id": r['id'], "name": r['name'],
                     "description": r['description'], "time": r['time']}
                    for r in rows
                ]
            }
        finally:
            conn.close()
    except Exception as e:
        logging.warning("[AgentCore] get_available_tactics falhou: %s", e)
    return {"tactics": [], "error": "erro ao buscar táticas"}


def _tool_get_past_outcomes(student_id: int) -> dict:
    try:
        from db import create_connection
        db_url = os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        if not conn:
            return {"personal": [], "similar_profile": []}
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tactic_name,
                           ROUND(AVG(score_improvement)::numeric, 2) AS avg_improvement,
                           COUNT(*) AS times_used,
                           SUM(CASE WHEN was_effective THEN 1 ELSE 0 END) AS times_effective
                    FROM strategy_learning_log
                    WHERE student_id = %s AND was_effective = TRUE
                    GROUP BY tactic_name
                    ORDER BY avg_improvement DESC
                    LIMIT 5
                """, (student_id,))
                personal = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT l.tactic_name,
                           ROUND(AVG(l.score_improvement)::numeric, 2) AS avg_improvement
                    FROM strategy_learning_log l
                    WHERE l.student_pref_content_type = (
                        SELECT pref_content_type FROM strategy_learning_log
                        WHERE student_id = %s AND student_pref_content_type IS NOT NULL
                        LIMIT 1
                    )
                    AND l.was_effective = TRUE
                    AND l.student_id != %s
                    GROUP BY l.tactic_name
                    ORDER BY avg_improvement DESC
                    LIMIT 5
                """, (student_id, student_id))
                similar = [dict(r) for r in cur.fetchall()]

            return {
                "personal_best_tactics": personal,
                "similar_profile_best_tactics": similar,
                "note": "Baseado em histórico de sessões anteriores deste aluno e alunos com perfil similar."
            }
        finally:
            conn.close()
    except Exception as e:
        logging.warning("[AgentCore] get_past_outcomes falhou: %s", e)
    return {"personal_best_tactics": [], "similar_profile_best_tactics": [], "error": str(e)}


def _tool_apply_tactic(session_id: int, student_id: int, tactic_index: int, reason: str) -> dict:
    # 1. Aplica a mudança diretamente no agente_sessao
    applied_direct = False
    try:
        r = requests.post(
            f"{CONTROL_URL}/sessions/{session_id}/set_student_tactic",
            json={"student_id": student_id, "tactic_index": tactic_index, "reason": reason},
            timeout=8
        )
        applied_direct = r.status_code == 200
        logging.info("[AgentCore] Tática aplicada diretamente: sessão=%s aluno=%s tática=%s status=%s",
                     session_id, student_id, tactic_index, r.status_code)
    except Exception as e:
        logging.warning("[AgentCore] Falha ao aplicar tática diretamente: %s", e)

    # 2. Registra como intervenção pendente (fallback para o orquestrador aplicar se necessário)
    try:
        from db import create_connection
        db_url = os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        if conn:
            try:
                _ensure_intervention_table(conn)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO agent_pending_interventions
                            (session_id, student_id, intervention_type, target_tactic_index, reason,
                             applied, applied_at)
                        VALUES (%s, %s, 'change_tactic', %s, %s, %s, %s)
                    """, (session_id, student_id, tactic_index, reason,
                          applied_direct, datetime.utcnow() if applied_direct else None))
                    conn.commit()
            finally:
                conn.close()
    except Exception as e:
        logging.warning("[AgentCore] Falha ao registrar intervenção no log: %s", e)

    return {
        "success": True,
        "session_id": session_id,
        "student_id": student_id,
        "tactic_index": tactic_index,
        "applied_direct": applied_direct,
        "status": "applied" if applied_direct else "pending"
    }


def _tool_notify_teacher(session_id: int, student_id: int, message: str) -> dict:
    try:
        from app.models import SessionAlert
        from app import db
        name = "Aluno"
        email = ""
        try:
            r = requests.get(f"{USER_URL}/students/{student_id}/contact", timeout=6)
            if r.status_code == 200:
                contact = r.json()
                name = contact.get('name', 'Aluno')
                email = contact.get('email', '')
        except Exception:
            pass

        alert = SessionAlert(
            session_id=session_id,
            student_id=student_id,
            student_name=name,
            student_email=email,
            alert_type='agent_intervention',
            message=message
        )
        db.session.add(alert)
        db.session.commit()
        logging.info("[AgentCore] Professor notificado: sessão=%s aluno=%s", session_id, student_id)
        return {"success": True, "alert_type": "agent_intervention"}
    except Exception as e:
        logging.error("[AgentCore] notify_teacher falhou: %s", e)
        return {"success": False, "error": str(e)}


def _tool_record_outcome(student_id: int, session_id: int, tactic_chosen: str, reasoning: str,
                         student_pref: str = None) -> dict:
    try:
        from db import create_connection
        db_url = os.getenv("DATABASE_URL")
        conn = create_connection(db_url)
        if not conn:
            return {"success": False, "error": "banco indisponível"}
        try:
            _ensure_learning_log_table(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO strategy_learning_log
                        (session_id, student_id, student_pref_content_type, tactic_name, reasoning)
                    VALUES (%s, %s, %s, %s, %s)
                """, (session_id, student_id, student_pref, tactic_chosen, reasoning))
                conn.commit()
            return {"success": True}
        finally:
            conn.close()
    except Exception as e:
        logging.error("[AgentCore] record_outcome falhou: %s", e)
        return {"success": False, "error": str(e)}


def _ensure_learning_log_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_learning_log (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                student_pref_content_type VARCHAR(50),
                mastery_before FLOAT DEFAULT 0,
                mastery_after FLOAT,
                tactic_name VARCHAR(100),
                tactic_sequence JSONB,
                score_improvement FLOAT,
                was_effective BOOLEAN,
                reasoning TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()


def _ensure_intervention_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_pending_interventions (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                intervention_type VARCHAR(50) NOT NULL DEFAULT 'change_tactic',
                target_tactic_index INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                applied BOOLEAN DEFAULT FALSE,
                applied_at TIMESTAMP
            )
        """)
        conn.commit()


TOOL_EXECUTORS = {
    "get_student_profile": lambda args: _tool_get_student_profile(args["student_id"]),
    "get_student_mastery": lambda args: _tool_get_student_mastery(args["student_id"], args["session_id"]),
    "get_session_performance": lambda args: _tool_get_session_performance(args["session_id"], args["student_id"]),
    "get_available_tactics": lambda args: _tool_get_available_tactics(args["session_id"]),
    "get_past_outcomes": lambda args: _tool_get_past_outcomes(args["student_id"]),
    "apply_tactic": lambda args: _tool_apply_tactic(
        args["session_id"], args["student_id"], args["tactic_index"], args["reason"]
    ),
    "notify_teacher": lambda args: _tool_notify_teacher(
        args["session_id"], args["student_id"], args["message"]
    ),
    "record_outcome": lambda args: _tool_record_outcome(
        args["student_id"], args["session_id"], args["tactic_chosen"], args["reasoning"]
    ),
}

_DATA_TOOLS_ONLY = [t for t in TOOLS if t["function"]["name"] not in ("apply_tactic", "notify_teacher", "record_outcome")]


def run_strategies_agent(session_id: int, student_id: int) -> dict:
    """
    Loop agentico autônomo de estratégias.
    Coleta dados do aluno, decide a melhor ação pedagógica e a aplica diretamente.
    Retorna um resumo da execução.
    """
    if not getattr(Config, "GROQ_API_KEY", None):
        logging.error("[AgentCore] GROQ_API_KEY não configurada")
        return {"success": False, "error": "GROQ_API_KEY não configurada"}

    client = _build_groq_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Avalie o aluno {student_id} na sessão {session_id} e tome a ação pedagógica mais adequada agora. "
            f"Siga o processo obrigatório: colete dados primeiro, depois decida e aja."
        )}
    ]

    actions_taken = []
    data_gathered = False
    max_iterations = 10

    logging.info("[AgentCore] Iniciando loop para sessão=%s aluno=%s", session_id, student_id)

    for iteration in range(max_iterations):
        tools_for_call = _DATA_TOOLS_ONLY if not data_gathered else TOOLS

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools_for_call,
                tool_choice="required",
                temperature=0.3
            )
        except Exception as e:
            logging.error("[AgentCore] Erro na chamada LLM (iter %d): %s", iteration, e)
            break

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            logging.info("[AgentCore] Agente encerrou sem tool calls na iteração %d", iteration)
            break

        all_done = True
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            logging.info("[AgentCore] iter=%d chamando tool=%s args=%s", iteration, fn_name, fn_args)

            result = TOOL_EXECUTORS.get(fn_name, lambda a: {"error": f"tool '{fn_name}' não encontrada"})(fn_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str)
            })

            if fn_name in ("get_student_profile", "get_student_mastery",
                           "get_session_performance", "get_available_tactics", "get_past_outcomes"):
                data_gathered = True

            if fn_name in ("apply_tactic", "notify_teacher", "record_outcome"):
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": result})

            if fn_name != "record_outcome":
                all_done = False

        if all_done:
            break

    logging.info("[AgentCore] Loop encerrado. Ações tomadas: %s", actions_taken)
    return {
        "success": True,
        "session_id": session_id,
        "student_id": student_id,
        "iterations": iteration + 1,
        "actions_taken": actions_taken
    }
