import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000/Calculadora_CCT_244_94_Alimentacion.html"

DAYS_SELECTORS = [
    "input[name='workedDays']",
    "input[name='daysWorked']",
    "input[name='worked-days']",
    "input[name='days']",
    "#worked-days",
    "#days-worked",
    "#workedDays",
    "#daysWorked",
    "input[type='number']"
]

AUDIT_GATE_SCENARIOS = [
pytest.param(
    {
        "worked_days": 30,
        "segments": [
            {"code": "ACTIVO", "from": 1, "to": 28}
        ],
        "expected_blocked": True,
    },
    id="tramo-revista-cubre-solo-28-bloquea",
),
pytest.param(
    {
        "worked_days": 30,
        "segments": [
            {"code": "ACTIVO", "from": 1, "to": 30}
        ],
        "expected_blocked": False,
    },
    id="tramo-revista-cubre-30-permite",
),
pytest.param(
    {
        "worked_days": 30,
        "segments": [
            {"code": "ACTIVO", "from": 1, "to": 15},
            {"code": "LICENCIA", "from": 16, "to": 30}
        ],
        "expected_blocked": False,
    },
    id="dos-tramos-completan-30-permite",
),
pytest.param(
    {
        "worked_days": 30,
        "segments": [
            {"code": "ACTIVO", "from": 1, "to": 20},
            {"code": "SUSPENSION", "from": 20, "to": 30}
        ],
        "expected_blocked": True,
    },
    id="tramos-solapados-bloquea",
),
pytest.param(
    {
        "worked_days": 30,
        "segments": [
            {"code": "ACTIVO", "from": 1, "to": 10},
            {"code": "LICENCIA", "from": 12, "to": 30}
        ],
        "expected_blocked": True,
    },
    id="tramos-con-hueco-bloquea",
),
]


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )


def visible_enabled(element):
    return element.is_displayed() and element.is_enabled()


def visible_controls_debug(driver):
    return driver.execute_script(
        """
        return Array.from(document.querySelectorAll('input, select, textarea, button')).map((el) => ({
          tag: el.tagName,
          type: el.type || '',
          id: el.id || '',
          name: el.name || '',
          text: el.innerText || el.value || '',
          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
          disabled: !!el.disabled
        })).filter((item) => item.visible && !item.disabled);
        """
    )


def first_visible(driver, selectors):
    if isinstance(selectors, str):
        selectors = [selectors]

    for selector in selectors:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        for element in elements:
            if visible_enabled(element):
                return element

    raise AssertionError(
        f"No se encontró elemento visible para selectores: {selectors}. Visibles: {visible_controls_debug(driver)}"
    )


def set_input_value(driver, element, value):
    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];
        input.scrollIntoView({ block: 'center', inline: 'nearest' });
        input.focus();
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        element,
        str(value),
    )


def click_element(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({ block: 'center' });", element)
    element.click()


def click_button_by_text(driver, *text_options):
    normalized_options = [text.lower() for text in text_options]
    buttons = driver.find_elements(By.CSS_SELECTOR, "button, a")
    for button in buttons:
        text = (button.text or "").lower()
        if visible_enabled(button) and any(option in text for option in normalized_options):
            click_element(driver, button)
            return button
    raise AssertionError(f"No se encontró botón visible con textos {text_options}. Visibles: {visible_controls_debug(driver)}")


def go_to_times_step(driver):
    candidates = driver.find_elements(By.CSS_SELECTOR, "[data-wizard-step], button, a")

    for candidate in candidates:
        text = (candidate.text or "").lower()
        step = candidate.get_attribute("data-wizard-step") or ""

        if visible_enabled(candidate) and (
            step == "times" or
            "novedades" in text or
            "tiempos" in text
        ):
            click_element(driver, candidate)
            return

    raise AssertionError(f"No se pudo navegar a Novedades y tiempos. Visibles: {visible_controls_debug(driver)}")


def prepare_audit_scenario(driver, worked_days):
    go_to_times_step(driver)
    days_input = first_visible(driver, DAYS_SELECTORS)
    set_input_value(driver, days_input, str(worked_days))
    click_button_by_text(driver, "continuar a conceptos")
    click_button_by_text(driver, "continuar a auditor", "auditoria preventiva", "auditoría preventiva")


def visible_result_buttons(driver):
    result_buttons = driver.find_elements(
        By.XPATH,
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'resultado')]"
    )
    return [button for button in result_buttons if button.is_displayed()]


@pytest.mark.parametrize("scenario", AUDIT_GATE_SCENARIOS)
def test_audit_gate_result_visibility_by_scenario(scenario):
    driver = create_driver()
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        prepare_audit_scenario(driver, scenario["worked_days"])

        if scenario["expected_blocked"]:
            wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'bloque')]"
                    )
                )
            )
            assert len(visible_result_buttons(driver)) == 0, (
                "El botón de continuar a resultado final sigue visible aun con auditoría bloqueante"
            )
        else:
            wait.until(lambda current_driver: len(visible_result_buttons(current_driver)) > 0)
            assert len(visible_result_buttons(driver)) > 0, (
                "El botón de resultado final debería estar visible cuando la auditoría no bloquea"
            )

    finally:
        driver.quit()
