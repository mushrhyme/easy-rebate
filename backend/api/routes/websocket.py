"""
WebSocket 실시간 통신 API
"""
import json
import asyncio
import os
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.websockets import WebSocketState
from backend.core.config import settings

router = APIRouter()


def is_local_network_origin(origin: str) -> bool:
    """로컬 네트워크 IP 또는 설정된 도메인인지 확인"""
    if not origin:
        return False
    try:
        # http:// 또는 https:// 제거
        url = origin.replace("http://", "").replace("https://", "")
        # 포트 제거
        host = url.split(":")[0]
        
        # localhost, 127.0.0.1 체크
        if host in ["localhost", "127.0.0.1"]:
            return True
        
        # LOCAL_IP 환경 변수에서 도메인 확인
        local_ip = os.getenv('LOCAL_IP', '')
        if local_ip:
            # http:// 또는 https:// 제거
            domain = local_ip.replace("http://", "").replace("https://", "")
            # 포트가 포함되어 있으면 제거
            if ":" in domain:
                domain = domain.split(":")[0]
            if host == domain:
                return True
        
        # 로컬 네트워크 IP 범위 체크
        parts = host.split(".")
        if len(parts) == 4:
            first = int(parts[0])
            second = int(parts[1])
            # 10.x.x.x, 172.16-31.x.x, 192.168.x.x
            if first == 10:
                return True
            if first == 172 and 16 <= second <= 31:
                return True
            if first == 192 and second == 168:
                return True
    except:
        pass
    return False


def is_allowed_origin(origin: str) -> bool:
    """origin이 허용된 origin인지 확인"""
    if not origin:
        return False
    
    # CORS_ORIGINS에 포함되어 있으면 허용
    if origin in settings.CORS_ORIGINS:
        return True
    
    # 개발 모드이거나 로컬 네트워크 origin이면 허용
    if settings.DEBUG or os.getenv("ALLOW_LOCAL_NETWORK", "true").lower() == "true":
        if is_local_network_origin(origin):
            return True
    
    return False


# 진행률 메시지 버퍼: 연결 전에 온 메시지를 보관했다가 첫 연결 시 전달 (레이스 컨디션 방지)
_MAX_PROGRESS_BUFFER = int(os.getenv("WS_PROGRESS_BUFFER_SIZE", "200"))


# 연결된 WebSocket 클라이언트 관리
class ConnectionManager:
    """WebSocket 연결 관리자"""
    
    def __init__(self):
        # {task_id: [websocket1, websocket2, ...]}
        self.active_connections: Dict[str, list] = {}
        # {page_key: [websocket1, websocket2, ...]} - 페이지별 락 구독
        self.page_subscriptions: Dict[str, list] = {}
        # {task_id: [msg, ...]} — 구독자 없을 때 쌓아두었다가 첫 연결 시 전송
        self.progress_buffers: Dict[str, list] = {}
    
    async def connect(self, websocket: WebSocket, task_id: str):
        """WebSocket 연결. 연결 직후 해당 task_id 버퍼 메시지를 전송한 뒤 버퍼 삭제."""
        await websocket.accept()
        
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        
        self.active_connections[task_id].append(websocket)
        
        # 연결 전에 온 진행률 메시지가 있으면 새 클라이언트에 전송
        if task_id in self.progress_buffers:
            for msg in self.progress_buffers[task_id]:
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json(msg)
                except Exception as e:
                    print(f"⚠️ WebSocket 버퍼 전송 실패: {e}")
                    break
            del self.progress_buffers[task_id]
    
    def disconnect(self, websocket: WebSocket, task_id: str):
        """WebSocket 연결 해제"""
        if task_id in self.active_connections:
            if websocket in self.active_connections[task_id]:
                self.active_connections[task_id].remove(websocket)
            
            # 연결이 없으면 task_id 제거
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        
        # 페이지 구독에서도 제거
        for page_key in list(self.page_subscriptions.keys()):
            if websocket in self.page_subscriptions[page_key]:
                self.page_subscriptions[page_key].remove(websocket)
            if not self.page_subscriptions[page_key]:
                del self.page_subscriptions[page_key]
    
    async def subscribe_page(self, websocket: WebSocket, pdf_filename: str, page_number: int):
        """페이지 락 상태 구독"""
        page_key = f"{pdf_filename}::{page_number}"
        if page_key not in self.page_subscriptions:
            self.page_subscriptions[page_key] = []
        if websocket not in self.page_subscriptions[page_key]:
            self.page_subscriptions[page_key].append(websocket)
    
    async def send_progress(self, task_id: str, message: dict):
        """진행률 메시지 전송. 구독자 없으면 버퍼에 저장 후 첫 연결 시 전송."""
        if task_id in self.active_connections:
            # 연결된 모든 클라이언트에 전송
            disconnected = []
            for websocket in self.active_connections[task_id]:
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json(message)
                    else:
                        disconnected.append(websocket)
                except Exception as e:
                    print(f"⚠️ WebSocket 전송 실패: {e}")
                    disconnected.append(websocket)
            for ws in disconnected:
                self.disconnect(ws, task_id)
        else:
            # 구독자 없음 → 버퍼에 저장 (최대 _MAX_PROGRESS_BUFFER개)
            if task_id not in self.progress_buffers:
                self.progress_buffers[task_id] = []
            buf = self.progress_buffers[task_id]
            buf.append(message)
            if len(buf) > _MAX_PROGRESS_BUFFER:
                self.progress_buffers[task_id] = buf[-_MAX_PROGRESS_BUFFER:]
    
    async def broadcast_lock_update(self, pdf_filename: str, page_number: int, message: dict):
        """페이지 락 상태 브로드캐스트"""
        page_key = f"{pdf_filename}::{page_number}"
        print(f"📢 [브로드캐스트] 시도: page_key={page_key}, message_type={message.get('type')}, item_id={message.get('item_id')}")
        print(f"   구독자 수: {len(self.page_subscriptions.get(page_key, []))}")
        print(f"   전체 구독 키: {list(self.page_subscriptions.keys())}")
        
        if page_key not in self.page_subscriptions:
            print(f"⚠️ [브로드캐스트] 구독자 없음: page_key={page_key}")
            return
        
        disconnected = []
        sent_count = 0
        for websocket in self.page_subscriptions[page_key]:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                    sent_count += 1
                    print(f"✅ [브로드캐스트] 전송 성공: {sent_count}번째 구독자")
                else:
                    print(f"⚠️ [브로드캐스트] WebSocket 상태 불량: state={websocket.client_state}")
                    disconnected.append(websocket)
            except Exception as e:
                print(f"⚠️ 락 브로드캐스트 실패: {e}")
                disconnected.append(websocket)
        
        print(f"✅ [브로드캐스트] 완료: 성공={sent_count}, 실패={len(disconnected)}")
        
        # 연결이 끊어진 소켓 제거
        for ws in disconnected:
            if page_key in self.page_subscriptions:
                if ws in self.page_subscriptions[page_key]:
                    self.page_subscriptions[page_key].remove(ws)

    async def broadcast_item_update(self, pdf_filename: str, page_number: int, message: dict):
        """아이템 업데이트 브로드캐스트 (생성/삭제 등)"""
        # broadcast_lock_update와 동일한 방식으로 구현
        await self.broadcast_lock_update(pdf_filename, page_number, message)


# 전역 연결 관리자
manager = ConnectionManager()


@router.websocket("/processing/{task_id}")
async def processing_status(websocket: WebSocket, task_id: str):
    """
    PDF 처리 진행률 실시간 전송
    
    Args:
        websocket: WebSocket 연결
        task_id: 작업 ID (세션 ID 또는 파일명)
    """
    # WebSocket 연결 허용 (CORS 체크)
    origin = websocket.headers.get("origin")
    print(f"🔌 WebSocket 연결 시도 (processing): task_id={task_id}, origin={origin}")
    
    # origin 체크
    if origin and not is_allowed_origin(origin):
        print(f"⚠️ WebSocket 연결 거부: origin={origin} not in allowed origins")
        print(f"   허용된 origins: {settings.CORS_ORIGINS}")
        await websocket.close(code=403, reason="Origin not allowed")
        return
    # elif origin:
    #     print(f"✅ WebSocket origin 허용: {origin}")
    
    try:
        # manager.connect에서 websocket.accept() 호출
        await manager.connect(websocket, task_id)
        # print(f"✅ WebSocket 연결 성공: task_id={task_id}")
    except Exception as e:
        print(f"❌ WebSocket 연결 실패: {e}")
        try:
            await websocket.close(code=1011, reason=f"Connection failed: {str(e)}")
        except:
            pass
        return
    
    try:
        # 연결 확인 메시지 전송
        await websocket.send_json({
            "type": "connected",
            "task_id": task_id,
            "message": "Connected to processing status"
        })
        
        # 클라이언트로부터 메시지 수신 대기 (연결 유지)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # ping/pong 메커니즘 (선택사항)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # 타임아웃 시 ping 전송
                await websocket.send_json({"type": "ping"})
    
    except WebSocketDisconnect:
        # 정상 종료(업로드 완료·탭 닫기 등). DEBUG일 때만 로그
        if settings.DEBUG:
            print(f"🔌 WebSocket 연결 종료: task_id={task_id}")
        manager.disconnect(websocket, task_id)
    except (OSError, ConnectionResetError) as e:
        # WinError 121(세마포어 타임아웃), 연결 끊김 등 — 클라이언트 비정상 종료 시 자주 발생
        if getattr(e, "winerror", None) != 121 and not isinstance(e, ConnectionResetError):
            print(f"⚠️ WebSocket OS 오류: task_id={task_id}, error={e}")
        manager.disconnect(websocket, task_id)
    except Exception as e:
        print(f"⚠️ WebSocket 오류: task_id={task_id}, error={e}")
        import traceback
        traceback.print_exc()
        manager.disconnect(websocket, task_id)


@router.websocket("/locks")
async def item_locks(websocket: WebSocket):
    """
    아이템 락 상태 실시간 구독
    연결 후 첫 메시지로 pdf_filename과 page_number를 전송해야 함
    
    첫 메시지 형식:
    {
        "type": "subscribe",
        "pdf_filename": "파일명.pdf",
        "page_number": 1
    }
    """
    # WebSocket 연결 허용 (CORS 체크)
    origin = websocket.headers.get("origin")
    print(f"🔌 WebSocket 연결 시도 (locks): origin={origin}")
    
    # origin 체크
    if origin and not is_allowed_origin(origin):
        print(f"⚠️ WebSocket 연결 거부: origin={origin} not in allowed origins")
        print(f"   허용된 origins: {settings.CORS_ORIGINS}")
        await websocket.close(code=403, reason="Origin not allowed")
        return
    elif origin:
        print(f" origin 허용: {origin}")
    
    try:
        await websocket.accept()
        # print(f"✅ WebSocket 연결 수락 (locks): origin={origin}")
    except Exception as e:
        print(f"❌ WebSocket accept 실패: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    pdf_filename = None
    page_number = None
    
    try:
        # 첫 메시지로 구독 정보 받기
        first_message = await websocket.receive_text()
        try:
            data = json.loads(first_message)
            if data.get("type") == "subscribe":
                pdf_filename = data.get("pdf_filename")
                page_number = data.get("page_number")
                
                if not pdf_filename or page_number is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "pdf_filename and page_number are required"
                    })
                    await websocket.close()
                    return
                
                await manager.subscribe_page(websocket, pdf_filename, page_number)
                # print(f"✅ [구독] 페이지 구독 완료: pdf_filename={pdf_filename}, page_number={page_number}")
                # print(f"   page_key: {pdf_filename}::{page_number}")
                
                # 현재 활성 락 목록 조회 (스레드 풀에서 실행)
                from database.registry import get_db
                current_locks = []
                try:
                    def _fetch_active_locks(database, pdf: str, page: int):
                        with database.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                SELECT il.item_id, il.locked_by_user_id
                                FROM item_locks_current il JOIN items_current i ON il.item_id = i.item_id
                                WHERE i.pdf_filename = %s AND i.page_number = %s AND il.expires_at > NOW()
                                UNION ALL
                                SELECT il.item_id, il.locked_by_user_id
                                FROM item_locks_archive il JOIN items_archive i ON il.item_id = i.item_id
                                WHERE i.pdf_filename = %s AND i.page_number = %s AND il.expires_at > NOW()
                            """, (pdf, page, pdf, page))
                            return [{"item_id": r[0], "locked_by": r[1]} for r in cursor.fetchall()]
                    db = get_db()
                    current_locks = await db.run_sync(_fetch_active_locks, db, pdf_filename, page_number)
                except Exception as e:
                    print(f"⚠️ [구독] 활성 락 조회 실패: {e}")
                    import traceback
                    traceback.print_exc()
                    current_locks = []
                
                # 연결 확인 메시지와 함께 현재 락 상태 전송
                await websocket.send_json({
                    "type": "connected",
                    "pdf_filename": pdf_filename,
                    "page_number": page_number,
                    "message": "Connected to lock updates",
                    "current_locks": current_locks
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": "First message must be type 'subscribe'"
                })
                await websocket.close()
                return
        except json.JSONDecodeError:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid JSON format"
            })
            await websocket.close()
            return
        
        # 클라이언트로부터 메시지 수신 대기 (연결 유지)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    if data == "ping":
                        await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    
    except WebSocketDisconnect:
        if pdf_filename and page_number is not None:
            manager.disconnect(websocket, "")
    except (OSError, ConnectionResetError) as e:
        # WinError 121(세마포어 타임아웃) 등 — 클라이언트 비정상 종료 시
        if getattr(e, "winerror", None) != 121 and not isinstance(e, ConnectionResetError):
            print(f"⚠️ 락 WebSocket OS 오류: {e}")
        if pdf_filename and page_number is not None:
            manager.disconnect(websocket, "")
    except Exception as e:
        print(f"⚠️ 락 WebSocket 오류: {e}")
        if pdf_filename and page_number is not None:
            manager.disconnect(websocket, "")


def send_progress_update(task_id: str, progress_data: dict):
    """
    진행률 업데이트 전송 (동기/비동기 함수에서 호출 가능)
    
    Args:
        task_id: 작업 ID
        progress_data: 진행률 데이터
            {
                "type": "progress",
                "file_name": "example.pdf",
                "current_page": 1,
                "total_pages": 10,
                "message": "Processing page 1/10"
            }
    """
    try:
        # 실행 중인 이벤트 루프 확인
        loop = asyncio.get_running_loop()
        # 이벤트 루프가 실행 중이면 create_task 사용
        asyncio.create_task(
            manager.send_progress(task_id, progress_data)
        )
    except RuntimeError:
        # 실행 중인 이벤트 루프가 없으면 (스레드에서 호출된 경우)
        # 메인 이벤트 루프를 찾아서 스레드 안전하게 실행
        try:
            # 메인 이벤트 루프 가져오기
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 루프가 실행 중이면 call_soon_threadsafe 사용
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        manager.send_progress(task_id, progress_data)
                    )
                )
            else:
                # 루프가 실행 중이 아니면 run_until_complete 사용
                loop.run_until_complete(
                    manager.send_progress(task_id, progress_data)
                )
        except RuntimeError:
            # 이벤트 루프를 찾을 수 없으면 새로 생성 (최후의 수단)
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    manager.send_progress(task_id, progress_data)
                )
                loop.close()
            except Exception as e:
                print(f"⚠️ WebSocket 진행률 전송 실패: {e}")
                # 실패해도 처리 계속 진행
