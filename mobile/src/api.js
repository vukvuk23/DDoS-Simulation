import { MITIGATION_BASE_URL } from './config';

export async function triggerScaleUp() {
  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/scale-up`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Scale up nije uspeo: ${response.status}`);
  return data;
}

export async function triggerScaleDown() {
  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/scale-down`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Scale down nije uspeo: ${response.status}`);
  return data;
}

export async function triggerRateLimit(average = 10, burst = 10) {
  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/ratelimit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ average, burst }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Rate limit nije uspeo: ${response.status}`);
  return data;
}

export async function triggerRateLimitReset() {
  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/ratelimit/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Reset nije uspeo: ${response.status}`);
  return data;
}