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


def test_audit_gate_blocks_result_button():
    driver = create_driver()
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(BASE_URL)

        wait.until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        days_input = wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "input[name='workedDays'], input[name='daysWorked'], #worked-days, #days-worked"
                )
            )
        )

        days_input.clear()
        days_input.send_keys("28")

        calculate_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button[type='submit'], #calculate-button, [data-action='calculate']"
                )
            )
        )
        calculate_button.click()

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
