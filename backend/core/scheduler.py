"""
스케줄러 설정 모듈

매월 1일 0시에 아카이브 마이그레이션을 자동 실행합니다.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

logger = logging.getLogger(__name__)


def setup_archive_scheduler():
    """
    아카이브 마이그레이션 스케줄러 설정
    
    Returns:
        AsyncIOScheduler 인스턴스
    """
    scheduler = AsyncIOScheduler()
    
    async def run_archive_migration():
        """아카이브 마이그레이션 실행 (비동기)"""
        try:
            logger.info("🔄 아카이브 마이그레이션 스케줄러 실행 시작")
            
            # 동기 함수를 비동기로 실행
            import asyncio
            from database.archive_migration import ArchiveMigration
            
            def sync_migration():
                migration = ArchiveMigration()
                migration.run_migration()
            
            # 별도 스레드에서 실행 (동기 함수이므로)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            await loop.run_in_executor(None, sync_migration)
            
            logger.info("✅ 아카이브 마이그레이션 스케줄러 실행 완료")
            
        except Exception as e:
            logger.error(f"❌ 아카이브 마이그레이션 스케줄러 실행 실패: {e}", exc_info=True)
    
    # 매월 1일 0시 0분 0초에 실행
    scheduler.add_job(
        run_archive_migration,
        trigger=CronTrigger(
            day=1,          # 매월 1일
            hour=0,          # 0시
            minute=0,        # 0분
            second=0,        # 0초
            timezone='Asia/Tokyo'  # 일본 시간대 (필요시 변경)
        ),
        id='archive_migration',
        name='아카이브 마이그레이션',
        replace_existing=True
    )
    
    logger.info("✅ 아카이브 마이그레이션 스케줄러 설정 완료 (매월 1일 0시 실행)")
    
    return scheduler
