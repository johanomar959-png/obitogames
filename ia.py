import ollama

model_name = "hf.co/bartowski/Qwen2.5-14B-Instruct-abliterated-GGUF:Q4_K_M"

stream = ollama.chat(
    model=model_name,
    messages=[
        {
            "role": "user",
            "content": "Explícame brevemente cómo funciona la recursividad.",
        },
    ],
    stream=True,
)

for chunk in stream:
    print(chunk["message"]["content"], end="", flush=True)