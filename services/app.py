import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import boto3
import os
import json
import time
from openai import OpenAI  # Ensure correct import for your needs
from .textract import TextractWrapper_Sincrono  # Ensure this import path is correct
import openai


client = OpenAI()
app = FastAPI()

def check_run(thread_id,run_id):
    run = openai.beta.threads.runs.retrieve(
        thread_id=thread_id,
        run_id=run_id
    )
    return run

def add_message(mensaje,thread_id):
    message = openai.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=mensaje
    )
    return message

import os

def get_insights(prompt):
    # Read the data from db.txt file
    print(os.getcwd())
    file_path = 'db.txt'
    try:
        with open(file_path, 'r') as file:
            file_contents = file.read().strip()
    except Exception as e:
        raise RuntimeError(f"Error reading from {file_path}: {e}")

    # Concatenate the file contents with the data
    full_content = (
        f"Use the data to solve the following prompt: {prompt} "
        f"Debes ser bastante específico y concreto en tus respuestas, no te extiendas mucho "
        f"Here is the data from where you need to do the analysis: {file_contents}"
    )

    # Create the completion
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": full_content}]
        )
    except Exception as e:
        raise RuntimeError(f"Error creating completion: {e}")

    return str(completion.choices[0].message.content)


def purify(data):
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "This is a json corresponding to the output of an ai model that extracts invoice data. Purify it so you give me a json with the relevant data of the invoice\n" + data + "\nGIVE ME ONLY THE JSON DATA WITHPUT ANY OTHER ADDITIONAL TEXT. ALSO SEND IT WITHPUT AND new line characters AND STUFF, ONLY THE PURE JSON. GIVE ME ALL LABELS AND INFO IN SPANISH"}
        ]
    )

    return str(completion.choices[0].message.content)

# Define the prompt function
def prompt(msg):
    assistant = client.beta.assistants.retrieve("asst_7c8AQaK10qYlAu4BDI2Z6ud6")
    thread = client.beta.threads.create()

    message = client.beta.threads.messages.create(
        thread.id,
        role="user",
        content=msg,
    )

    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )

    while run.status != "completed":
        time.sleep(0.5)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run.status == 'requires_action':
            time.sleep(0.5)
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            
            if tool_calls:
                available_functions = {
                    "get_insights": get_insights
                    }
                
                tool_outputs = []

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_to_call = available_functions.get(function_name)

                    if function_to_call:
                        # Parsear argumentos de la función
                        argumentos_parseados = json.loads(tool_call.function.arguments)
                        
                        # Llamada a la función correspondiente
                        respuesta_funcion = function_to_call(**argumentos_parseados)

                        #print(f"se ha invocado la función {function_name}\n{respuesta_funcion}")

                        #print("RPAI:", respuesta_funcion)
                        #send_whatsapp_message(respuesta_funcion)

                        run = check_run(thread.id,run.id)
                        if run.status == 'expired':
                            add_message(f"La funcion {function_to_call}, no se completo. Continua el proceso a partir de este paso.",thread_id)
                            break
                        else:
                            # Agregar la salida de la herramienta a la lista  
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": respuesta_funcion,
                            })

                # Enviar todas las salidas de las herramientas después de procesarlas
                if tool_outputs:
                    run = openai.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )

    messages = client.beta.threads.messages.list(thread.id)
    response = messages.data[0].content[0].text.value

    return response



# Fetch AWS credentials from environment variables
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
region_name = 'us-east-1'  # Set your AWS region

# Initialize Boto3 clients/resources with region specified
textract_client = boto3.client(
    'textract', 
    region_name=region_name, 
    aws_access_key_id=aws_access_key_id, 
    aws_secret_access_key=aws_secret_access_key
)
s3_resource = boto3.resource(
    's3', 
    region_name=region_name, 
    aws_access_key_id=aws_access_key_id, 
    aws_secret_access_key=aws_secret_access_key
)
sqs_resource = boto3.resource(
    'sqs', 
    region_name=region_name, 
    aws_access_key_id=aws_access_key_id, 
    aws_secret_access_key=aws_secret_access_key
)

# Initialize TextractWrapper_Sincrono instance
textract_wrapper = TextractWrapper_Sincrono(textract_client, s3_resource, sqs_resource)

class InvoiceDataResponse(BaseModel):
    cleaned_response: dict

class InvoiceTextRequest(BaseModel):
    text: str

@app.post("/extract-invoice-data/", response_model=InvoiceDataResponse)
async def extract_invoice_data(file: UploadFile = File(...)):
    try:
        # Read the file contents
        file_bytes = await file.read()
        # Call detect_invoice_data
        raw_response, cleaned_response = textract_wrapper.detect_invoice_data(document_bytes=file_bytes)
        
        # Call the purify function to clean the data
        ans = purify(json.dumps(cleaned_response))
        
        if ans is None:
            raise HTTPException(status_code=500, detail="Error in purify function.")
        
        # Ensure the response is a valid JSON object
        parsed_response = json.loads(ans)
        
        return InvoiceDataResponse(cleaned_response=parsed_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-invoice-text/")
async def process_invoice_text(request: InvoiceTextRequest):
    try:
        # Call the prompt function to process the text
        result = prompt(request.text)
        return {"processed_response": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)