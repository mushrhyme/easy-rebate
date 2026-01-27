# API 사용 예제

## 1. 문서 업로드

### 단일 파일 업로드

```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "form_type=01" \
  -F "files=@example.pdf"
```

### 다중 파일 업로드

```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "form_type=01" \
  -F "files=@file1.pdf" \
  -F "files=@file2.pdf" \
  -F "files=@file3.pdf"
```

### 응답 예제

```json
{
  "message": "Files uploaded",
  "results": [
    {
      "filename": "example.pdf",
      "status": "pending",
      "pdf_name": "example"
    }
  ],
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 2. 문서 목록 조회

### 전체 문서

```bash
curl "http://localhost:8000/api/documents"
```

### 양식지별 필터링

```bash
curl "http://localhost:8000/api/documents?form_type=01"
```

### 응답 예제

```json
{
  "documents": [
    {
      "pdf_filename": "example.pdf",
      "total_pages": 5,
      "form_type": "01",
      "status": "completed"
    }
  ],
  "total": 1
}
```

## 3. 특정 문서 조회

```bash
curl "http://localhost:8000/api/documents/example.pdf"
```

## 4. 문서 삭제

```bash
curl -X DELETE "http://localhost:8000/api/documents/example.pdf"
```

## 5. 페이지의 아이템 조회

```bash
curl "http://localhost:8000/api/items/example.pdf/pages/1"
```

### 응답 예제

```json
{
  "items": [
    {
      "item_id": 1,
      "pdf_filename": "example.pdf",
      "page_number": 1,
      "item_order": 1,
      "customer": "取引先名",
      "product_name": "商品名",
      "item_data": {
        "管理番号": "12345",
        "数量": 100,
        "金額": 10000
      },
      "review_status": {
        "first_review": {"checked": false},
        "second_review": {"checked": false}
      },
      "version": 1
    }
  ]
}
```

## 6. 아이템 업데이트

```bash
curl -X PUT "http://localhost:8000/api/items/1" \
  -H "Content-Type: application/json" \
  -d '{
    "item_data": {
      "管理番号": "12345",
      "数量": 200,
      "金額": 20000
    },
    "review_status": {
      "first_review": {"checked": true},
      "second_review": {"checked": false}
    },
    "expected_version": 1,
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

## 7. 아이템 락 획득

```bash
curl -X POST "http://localhost:8000/api/items/1/lock" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

## 8. 아이템 락 해제

```bash
curl -X DELETE "http://localhost:8000/api/items/1/lock" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

## 9. 거래처명으로 검색

```bash
curl "http://localhost:8000/api/search/customer?customer_name=取引先名&exact_match=false&form_type=01"
```

### 응답 예제

```json
{
  "query": "取引先名",
  "total_items": 10,
  "total_pages": 3,
  "pages": [
    {
      "pdf_filename": "example.pdf",
      "page_number": 1,
      "items": [...],
      "form_type": "01"
    }
  ]
}
```

## 10. 페이지 이미지 조회

```bash
curl "http://localhost:8000/api/search/example.pdf/pages/1/image"
```

### 응답 예제

```json
{
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "format": "jpeg"
}
```

## 11. WebSocket 연결 (JavaScript)

```javascript
// 연결
const ws = new WebSocket('ws://localhost:8000/ws/processing/session-id');

// 메시지 수신
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch (data.type) {
    case 'connected':
      console.log('Connected:', data.message);
      break;
    case 'start':
      console.log('Processing started:', data.file_name);
      break;
    case 'progress':
      console.log(`Progress: ${data.current_page}/${data.total_pages}`);
      console.log(`Message: ${data.message}`);
      // 진행률 바 업데이트
      updateProgressBar(data.progress);
      break;
    case 'complete':
      console.log('Processing completed:', data);
      break;
    case 'error':
      console.error('Processing error:', data.error);
      break;
    case 'ping':
      // ping에 대한 pong 응답 (자동 처리)
      break;
  }
};

// 연결 오류 처리
ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

// 연결 종료 처리
ws.onclose = () => {
  console.log('WebSocket closed');
};

// ping 전송 (연결 유지)
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send('ping');
  }
}, 30000); // 30초마다
```

## 12. Python 클라이언트 예제

```python
import requests
import websocket
import json

# 파일 업로드
files = [('files', open('example.pdf', 'rb'))]
data = {'form_type': '01'}
response = requests.post(
    'http://localhost:8000/api/documents/upload',
    files=files,
    data=data
)
result = response.json()
session_id = result['session_id']

# WebSocket 연결
def on_message(ws, message):
    data = json.loads(message)
    print(f"Progress: {data}")

ws = websocket.WebSocketApp(
    f'ws://localhost:8000/ws/processing/{session_id}',
    on_message=on_message
)
ws.run_forever()
```
