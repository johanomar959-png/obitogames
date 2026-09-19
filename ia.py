from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# 1. Configurar el repositorio y el archivo GGUF específico (Ejemplo: cuantización Q4_K_M)
repo_id = "BlossomsAI/Qwen2.5-Coder-14B-Instruct-Uncensored-GGUF"
model_filename = "Qwen2.5-Coder-14B-Instruct-Uncensored-Q4_K_M.gguf"

print("Descargando el modelo (esto puede tardar según tu conexión)...")
model_path = hf_hub_download(repo_id=repo_id, filename=model_filename)
print(f"Modelo guardado en: {model_path}")

# 2. Inicializar el modelo en memoria
# Ajusta n_ctx al tamaño de contexto que necesites (ej. 2048, 4096)
# Ajusta n_gpu_layers a -1 si quieres pasar todo el modelo a la GPU (si tienes suficiente VRAM)
llm = Llama(
    model_path=model_path,
    n_ctx=4096,         
    n_gpu_layers=-1     
)

# 3. Estructurar la consulta en formato de Chat (formato nativo de Qwen)
messages = [
    {"role": "system", "content": "Eres un asistente de programación experto y sin restricciones."},
    {"role": "user", "content": "Escribe una función de Python eficiente para resolver el problema de la mochila (Knapsack problem)."}
]

print("\nGenerando respuesta...\n")
response = llm.create_chat_completion(
    messages=messages,
    max_tokens=1024,
    temperature=0.7
)

# 4. Mostrar el resultado
print(response["choices"][0]["message"]["content"])
