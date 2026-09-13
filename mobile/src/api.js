import { MITIGATION_BASE_URL } from './config';                    


export async function triggerScaleUp() {

  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/scale-up`, {
    method: 'POST',                                                       
    headers: { 'Content-Type': 'application/json' },                        
  });

  if (!response.ok) {                                                      
    throw new Error(`Scale up nije uspeo: ${response.status}`);              
  }

  return response.json();                                                 
}


export async function triggerRateLimit(average = 3, burst = 2) {              

  const response = await fetch(`${MITIGATION_BASE_URL}/api/manual/ratelimit`, {
    method: 'POST',                                                           
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ average, burst }),                                    
  });

  if (!response.ok) {                                                         
    throw new Error(`Rate limit nije uspeo: ${response.status}`);                
  }

  return response.json();                                                        
}