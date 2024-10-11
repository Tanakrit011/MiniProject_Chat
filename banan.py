from neo4j import GraphDatabase
from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from sentence_transformers import SentenceTransformer, util,InputExample
from sentence_transformers import models, losses
from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator
from torch.utils.data import DataLoader
import numpy as np
import requests



#model = SentenceTransformer('bert-base-nli-mean-tokens')
model = SentenceTransformer('sentence-transformers/distiluse-base-multilingual-cased-v2')
import json
# URI examples: "neo4j://localhost", "neo4j+s://xxx.databases.neo4j.io"
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "test")


# Function to get response from Llama3
def get_llama_response(prompt):
   OLLAMA_API_URL = "http://localhost:11434/api/generate"
   headers = {
      "Content-Type": "application/json"
   }
   
   role_prompt = f"ผู้ตอบเป็นชาวสวนกล้วยผู้ชาย ให้คำแนะนำเกี่ยวกับ: {prompt} โดยคำตอบยาวไม่เกิน 20 คำ"
   
   payload = {
      "model": "supachai/llama-3-typhoon-v1.5",
      "prompt": role_prompt,
      "stream": False
   }
   
   response = requests.post(OLLAMA_API_URL, headers=headers, data=json.dumps(payload))
   
   if response.status_code == 200:
      response_data = response.text
      data = json.loads(response_data)
      return data.get("response", "ขอโทษด้วย ฉันไม่สามารถให้คำตอบนี้ได้")  # Default message if response not found
   else:
      print(f"Failed to get a response: {response.status_code}, {response.text}")
      return "ขอโทษด้วย ฉันไม่สามารถให้คำตอบนี้ได้"

def run_query(query, parameters=None):
   with GraphDatabase.driver(URI, auth=AUTH) as driver:
       driver.verify_connectivity()
       with driver.session() as session:
           result = session.run(query, parameters)
           return [record for record in result]
   driver.close()


cypher_query = '''
MATCH (n:Question) RETURN n.question as question, n.answer as reply;
'''
greeting_corpus = []
greeting_vec = None
results = run_query(cypher_query)
for record in results:
   greeting_corpus.append(record['question'])
greeting_corpus = list(set(greeting_corpus))
print(greeting_corpus)  


def save_question_to_neo4j(question, reply):
   # Create a new node for the Llama3 response in the Neo4j database
   create_query = '''
   CREATE (:Question {question: $question, answer: $reply});
   '''
   parameters = {"question": question, "reply": reply}
   run_query(create_query, parameters)


def compute_similar(corpus, sentence):
   a_vec = model.encode([corpus],convert_to_tensor=True,normalize_embeddings=True)
   b_vec = model.encode([sentence],convert_to_tensor=True,normalize_embeddings=True)
   similarities = util.cos_sim(a_vec, b_vec)
   return similarities

def update_greeting_corpus():
   cypher_query = '''
   MATCH (n:Question) RETURN n.question as question;
   '''
   results = run_query(cypher_query)
   updated_corpus = [record['question'] for record in results]
   return list(set(updated_corpus))


def neo4j_search(neo_query):
   results = run_query(neo_query)
   # Print results
   for record in results:
       response_msg = record['reply']
   return response_msg     


def compute_response(sentence):
   global greeting_corpus  # Declare the global variable at the start

   # Encoding vectors for comparison
   greeting_vec = model.encode(greeting_corpus, convert_to_tensor=True, normalize_embeddings=True)
   ask_vec = model.encode(sentence, convert_to_tensor=True, normalize_embeddings=True)
   greeting_scores = util.cos_sim(greeting_vec, ask_vec)
   greeting_np = greeting_scores.cpu().numpy()

   max_greeting_score = np.argmax(greeting_np)
   Match_greeting = greeting_corpus[max_greeting_score]

   if greeting_np[max_greeting_score] > 0.7:
      My_cypher = f"MATCH (n:Question) where n.question ='{Match_greeting}' RETURN n.answer as reply"
      response_msg = neo4j_search(My_cypher)

      # Limit response to 20 tokens (words)
      token_limit = 20
      response_tokens = response_msg.split()
      if len(response_tokens) > token_limit:
         response_msg = ' '.join(response_tokens[:token_limit])

      print(response_msg)
      return response_msg + 'ครับ'
   else:
      # Use Llama3 for undefined responses
      llama_response = get_llama_response(sentence)
      
      # Save the Llama3 response to Neo4j
      save_question_to_neo4j(sentence, llama_response)
      
      # Update the greeting_corpus to include the new question
      greeting_corpus = update_greeting_corpus()  # Update the corpus with new questions
      
      return llama_response






app = Flask(__name__)




@app.route("/", methods=['POST'])
def linebot():
   body = request.get_data(as_text=True)                   
   try:
       json_data = json.loads(body)                       
       access_token = 'cHxsjwyF5E6yAEUPqGaY6/DF6oO4+Zx+rGZvj/+Zii1bHZwqxiS2mpCI7hsdr0sZW4ViQJileO/cuOtXd87NoO23klp5KEPhx8+EVWKA4BUHYqMiERp7FXePb9bYMoLVGMymig+yhC2QmC3QwRRMggdB04t89/1O/w1cDnyilFU='
       secret = '8862390e821c75a329bbb5846d6dc936'
       line_bot_api = LineBotApi(access_token)             
       handler = WebhookHandler(secret)                   
       signature = request.headers['X-Line-Signature']     
       handler.handle(body, signature)                     
       msg = json_data['events'][0]['message']['text']     
       tk = json_data['events'][0]['replyToken']           
       response_msg = compute_response(msg)
       print("Response message:", response_msg)  # Debug line
       line_bot_api.reply_message( tk, TextSendMessage(text=response_msg) )
       print(msg, tk)                                     
   except Exception as e:
        print("Error occurred:", str(e))  # Print the error                                       
   return 'OK'               
if __name__ == '__main__':
   # #For Debug
   # compute_response("นอนหลับฝันดี")
   app.run(port=5000)