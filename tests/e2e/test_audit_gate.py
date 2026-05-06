from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000/Calculadora_CCT_244_94_Alimentacion.html"


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


def first_visible(driver, selector):
    elements = driver.find_elements(By.CSS_SELECTOR, selector)
    for element in elements:
        if element.is_displayed() and element.is_enabled():
            return element
    raise AssertionError(f"No se encontró elemento visible para selector: {selector}")


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


def click_visible(driver, selector):
    element = first_visible(driver, selector)
    driver.execute_script("arguments[0].scrollIntoView({ block: 'center' });", element)
    element.click()
    return element


def test_audit_gate_blocks_result_button():
    driver = create_driver()
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(BASE_URL)

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        days_input = first_visible(
            driver,
            "input[name='workedDays'], input[name='daysWorked'], #worked-days, #days-worked"
        )
        set_input_value(driver, days_input, "28")

        click_visible(driver, "button[type='submit'], #calculate-button, [data-action='calculate']")

        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'bloque')]"
                )
            )
        )

        result_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'resultado')]"
        )

        visible_buttons = [button for button in result_buttons if button.is_displayed()]

        assert len(visible_buttons) == 0, (
            "El botón de continuar a resultado final sigue visible aun con auditoría bloqueante"
        )

    finally:
        driver.quit()
