from backend.app import (
    CHAT_NO_INFO_MESSAGE,
    build_calculator_chat_records,
    build_local_calculator_chat_answer,
    rank_calculator_chat_records,
)


def test_calculator_chat_answers_from_loaded_scale():
    calculator = {
        "convenio": {"nombre": "Demo CCT"},
        "categorias": [{"nombre": "Oficial", "basico_mensual": 1000}],
    }

    records = build_calculator_chat_records(calculator)
    matches = rank_calculator_chat_records("categorias y basico oficial", records)
    answer = build_local_calculator_chat_answer("categorias y basico oficial", matches)

    assert "Oficial" in answer
    assert "$1.000,00" in answer


def test_calculator_chat_says_no_info_when_context_does_not_match():
    calculator = {
        "convenio": {"nombre": "Demo CCT"},
        "categorias": [{"nombre": "Oficial", "basico_mensual": 1000}],
    }

    records = build_calculator_chat_records(calculator)
    matches = rank_calculator_chat_records("licencia por mudanza", records)

    assert build_local_calculator_chat_answer("licencia por mudanza", matches) == CHAT_NO_INFO_MESSAGE
