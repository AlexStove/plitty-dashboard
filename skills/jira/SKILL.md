---
name: jira_integration
description: Интеграция с Jira Data Center (jira.atomcorp.org) для ведения отчета задач, списывания рабочего времени (worklog), автоматического тайм-трекинга (старт/стоп) и поиска тасок.
---

# Интеграция с Jira Data Center

Данный навык позволяет управлять задачами и списывать рабочее время в Jira Data Center (https://jira.atomcorp.org).

## Конфигурация
Настройки подключения хранятся в файле:
`C:\Users\a.feoktistov\.gemini\config\skills\jira\config.json`

## Автоматический тайм-трекинг (Фиксация времени)

Когда пользователь пишет фразы вида:
- **«Взял TAU-27»**, **«Начал работу над TAU-27»**, **«Старт TAU-27»**
  -> Запусти таймер:
  `python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py start-timer TAU-27`

- **«Закончил TAU-27»**, **«Завершил TAU-27»**, **«Сделал TAU-27»**
  -> Останови таймер, автоматически посчитай время работы и залогируй его в Jira с комментариями времени (с HH:MM по HH:MM):
  `python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py stop-timer TAU-27 -m "произвольный комментарий"`

- **«Какие таймеры запущены?»**
  -> `python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py list-timers`

---

## Другие команды Jira

### 1. Проверка соединения
```bash
python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py test
```

### 2. Создание новой задачи
```bash
python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py create TAU "Заголовок задачи" -d "Описание задачи"
```

### 3. Ручной Worklog (списание времени)
```bash
python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py worklog TAU-123 "2h 30m" -m "Разработка функции"
```

### 4. Получение деталей задачи
```bash
python C:\Users\a.feoktistov\.gemini\config\skills\jira\jira_cli.py get TAU-123
```
