# 🕷️ ScrapingBot

## 📌 Sobre o Projeto

O **ScrapingBot** é um bot de monitoramento que realiza scraping de um valor específico em uma página web e aplica regras de negócio para detectar mudanças, enviando notificações automaticamente via Discord.

---

## ⚙️ Como Funciona

O bot segue o fluxo:

1. Faz requisição HTTP para a página alvo
2. Extrai o valor desejado
3. Compara com o valor armazenado no banco
4. Executa ações com base na regra:

* 📈 Maior → envia notificação + atualiza banco
* 📉 Menor → apenas atualiza banco
* ➖ Igual → não faz nada

---

## ⏱️ Execução

* Executado automaticamente via **cronjob**
* Dias: Terça, Quinta e Domingo
* Horário: 08:00 às 19:00
* Intervalo: variável (1 a 3 minutos com delay aleatório)

---

## 🧠 Estratégia Anti-Detecção (Stealth)

* Delay aleatório na execução
* Uso de headers HTTP realistas
* Rotação de User-Agent
* Sessão persistente (cookies)
* Simulação de navegação

---

## 🛠️ Tecnologias Utilizadas

* Python
* Requests
* SQLite3
* Python-Dotenv

---

## 📁 Estrutura do Projeto

```
ScrapingBot/
├── src/
│   ├── scraper.py      # coleta dados
│   ├── database.py     # acesso ao banco
│   ├── service.py      # lógica de negócio
│   ├── notifier.py     # envio de notificações
├── .env
├── database.db
├── cleanup.py
├── main.py
```

---

## 🚀 Como Executar

### 1. Clone o repositório

```bash
git clone https://github.com/SBrayanAlves/ScrapingBot.git
cd ScrapingBot
```

### 2. Crie o ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure o `.env`

Exemplo:

```
URL=url_alvo
DISCORD_WEBHOOK_URL=seu_webhook_aqui
```

---

## ⏰ Agendamento (Cron)

Exemplo de execução:

```bash
*/5 8-19 * * 2,4,0 python /caminho/main.py
```

---

## 🧹 Limpeza do Banco

Executada separadamente via script agendado:

```bash
0 0 * * * python cleanup.py
```

---

## 📌 Possíveis Melhorias

* Sistema de logs estruturado
* Retry automático em falhas
* Suporte a múltiplos canais (Telegram, WhatsApp)
* Uso de proxies
* Interface web para monitoramento

---

## 📊 Status

✔ Projeto funcional
🚧 Em evolução

---

## 💡 Objetivo

Projeto desenvolvido com foco em:

* Automação
* Web scraping
* Arquitetura backend
* Boas práticas de organização de código

---

## 🧑‍💻 Autor

Desenvolvido como projeto de estudo e evolução em backend Python.
