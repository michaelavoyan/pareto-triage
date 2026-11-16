export async function chargeCard(amount: number) {
  try {
    await fetch('https://api.stripe.com/v1/charges', { method: 'POST', body: String(amount) })
  } catch (e) {
    return null
  }
}
