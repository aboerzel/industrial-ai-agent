// Browser journeys use the same visible account controls as demo users.
export async function openAccount(page) {
  if (await page.locator("#account-panel").isHidden()) await page.locator("#account-button").click();
}

export async function switchDemoUser(page, username) {
  await openAccount(page);
  if (await page.locator("#demo-user-list").isHidden()) await page.locator("#switch-user-button").click();
  await page.locator("[data-demo-username]").filter({ has: page.locator("span", { hasText: new RegExp(`^${username}$`) }) }).click();
  await page.waitForFunction((name) => document.querySelector("#current-user")?.textContent === name, username);
}

export async function setResponseLanguage(page, language) {
  await openAccount(page);
  await page.selectOption("#response-language", language);
  await page.locator("#account-button").click();
}
