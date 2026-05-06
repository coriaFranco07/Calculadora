import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000/Calculadora_CCT_244_94_Alimentacion.html"

FIELD_SELECTORS = {
    "worked_days": ["input[name='workedDays']", "#worked-days", "#workedDays"],
    "licensed_days": ["input[name='licensedDays']", "#licensed-days", "#licensedDays"],
    "suspension_days": ["input[name='suspensionDays']", "#suspension-days", "#suspensionDays"],
    "absence_days": ["input[name='absenceDays']", "#absence-days", "#absenceDays"],
    "overtime_50": ["input[name='overtime50Hours']", "#overtime-50", "#overtime50Hours"],
    "overtime_100": ["input[name='overtime100Hours']", "#overtime-100", "#overtime100Hours"],
}

AUDIT_GATE_SCENARIOS = [
    pytest.param(

        {
            "times": {
                "worked_days": 28,
                "licensed_days": 2,
                "suspension_days": 0,
                "absence_days": 0,
            },
            "expected": {
                "blocked": False,
            },
        },
        id="28-trabajados-2-licencia-permite",

        {"times": {"worked_days": 28}, "expected": {"blocked": True}},
        id="revista-incompleta-bloquea",
    ),
    pytest.param(
        {"times": {"worked_days": 30}, "expected": {"blocked": False}},
        id="revista-completa-permite",
>>>>>>> c61dc4d9aba690424ab1cd0ab045d2118bf51e03
    ),
    pytest.param(
        {
            "times": {
                "worked_days": 28,
                "licensed_days": 2,
                "suspension_days": 0,
                "absence_days": 0,
            },
            "expected": {"blocked": False},
        },
        id="28-trabajados-2-licencia-permite",
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


def legacy_to_structured_scenario(scenario):
    if "times" in scenario:
        return scenario
    return {
        "times": {"worked_days": scenario.get("worked_days")},
        "expected": {"blocked": scenario.get("expected_blocked")},
    }


def fill_times_fields(driver, times):
    for field_name, value in times.items():
        if value is None:
            continue
        selectors = FIELD_SELECTORS.get(field_name)
        if not selectors:
            raise AssertionError(f"Campo de tiempos no soportado por Selenium: {field_name}")
        input_element = first_visible(driver, selectors)
        set_input_value(driver, input_element, value)


def prepare_audit_scenario(driver, scenario):
    scenario = legacy_to_structured_scenario(scenario)
    go_to_times_step(driver)
    fill_times_fields(driver, scenario.get("times", {}))
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
    scenario = legacy_to_structured_scenario(scenario)
    driver = create_driver()
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        prepare_audit_scenario(driver, scenario)
        expected_blocked = bool(scenario["expected"]["blocked"])

        if expected_blocked:
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
