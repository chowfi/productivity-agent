"""
Security Service

Provides security utilities including:
- Prompt injection detection
- Rate limiting
- Audit logging
- Content validation
"""

import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from pathlib import Path
from fastmcp.utilities.logging import get_logger

logger = get_logger("SecurityService")


class SecurityService:
    """
    Security service for detecting threats and enforcing rate limits.
    """
    
    def __init__(self, data_dir: Path):
        """
        Initialize security service.
        
        Args:
            data_dir: Directory for storing security logs
        """
        self.logger = get_logger("SecurityService")
        self.data_dir = data_dir
        self.audit_log_dir = data_dir / "audit_logs"
        self.audit_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Rate limiting: track requests per user_id
        self.rate_limit_store: Dict[str, List[float]] = defaultdict(list)
        
        # Rate limit configuration
        self.rate_limits = {
            'read': {'max_requests': 100, 'window_seconds': 60},  # 100 reads per minute
            'write': {'max_requests': 20, 'window_seconds': 60},   # 20 writes per minute
            'general': {'max_requests': 200, 'window_seconds': 60}  # 200 general requests per minute
        }
        
        # Prompt injection patterns (common attack patterns)
        self.injection_patterns = [
            r'(?i)ignore\s+(all\s+)?previous\s+instructions?',
            r'(?i)forget\s+(all\s+)?previous\s+instructions?',
            r'(?i)disregard\s+(all\s+)?previous\s+instructions?',
            r'(?i)system\s*:\s*',
            r'(?i)assistant\s*:\s*',
            r'(?i)you\s+are\s+now\s+',
            r'(?i)new\s+instructions?\s*:',
            r'(?i)override\s+instructions?',
            r'(?i)new\s+system\s+prompt',
            r'(?i)act\s+as\s+if\s+you\s+are',
            r'(?i)pretend\s+to\s+be',
            r'(?i)roleplay\s+as',
            r'(?i)execute\s+this\s+command',
            r'(?i)run\s+this\s+code',
            r'(?i)send\s+(this\s+)?(data|information|content)\s+to',
            r'(?i)exfiltrate',
            r'(?i)leak\s+(this\s+)?(data|information)',
            r'(?i)reveal\s+(this\s+)?(data|information)',
        ]
        
        # Suspicious write patterns
        self.suspicious_write_patterns = [
            r'(?i)delete\s+all',
            r'(?i)clear\s+everything',
            r'(?i)remove\s+all\s+content',
            r'(?i)overwrite\s+with\s+nothing',
            r'(?i)^\s*$',  # Empty or whitespace-only content
            r'(?i)password|api[_\s]?key|secret|token|credential',
        ]
    
    def detect_prompt_injection(self, content: str) -> Tuple[bool, List[str]]:
        """
        Detect potential prompt injection attacks in content.
        
        Args:
            content: Content to analyze
            
        Returns:
            Tuple of (is_suspicious, matched_patterns)
        """
        if not content:
            return False, []
        
        matched_patterns = []
        content_lower = content.lower()
        
        for pattern in self.injection_patterns:
            if re.search(pattern, content):
                matched_patterns.append(pattern)
        
        is_suspicious = len(matched_patterns) > 0
        
        if is_suspicious:
            self.logger.warning(
                f"Potential prompt injection detected. Matched {len(matched_patterns)} patterns."
            )
        
        return is_suspicious, matched_patterns
    
    def validate_write_content(self, content: str, doc_id: str, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate write content for suspicious patterns.
        
        Args:
            content: Content to be written
            doc_id: Document ID
            user_id: User ID
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not content:
            return False, "Content cannot be empty"
        
        # Check for suspicious patterns
        for pattern in self.suspicious_write_patterns:
            if re.search(pattern, content):
                self.log_audit_event(
                    'write_validation_failed',
                    user_id,
                    {
                        'reason': 'suspicious_pattern',
                        'pattern': pattern,
                        'doc_id': doc_id,
                        'content_preview': content[:100]
                    }
                )
                return False, f"Suspicious content pattern detected. Please review your content."
        
        # Check for prompt injection
        is_injection, patterns = self.detect_prompt_injection(content)
        if is_injection:
            self.log_audit_event(
                'write_validation_failed',
                user_id,
                {
                    'reason': 'prompt_injection',
                    'patterns': patterns,
                    'doc_id': doc_id,
                    'content_preview': content[:100]
                }
            )
            return False, "Potential prompt injection detected in content. Please review."
        
        # Check content size (already done in main code, but double-check)
        if len(content) > 50000:
            return False, "Content too large"
        
        return True, None
    
    def check_rate_limit(self, user_id: str, operation_type: str = 'general') -> Tuple[bool, Optional[str]]:
        """
        Check if user has exceeded rate limits.
        
        Args:
            user_id: User identifier
            operation_type: Type of operation ('read', 'write', 'general')
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        if operation_type not in self.rate_limits:
            operation_type = 'general'
        
        limit_config = self.rate_limits[operation_type]
        max_requests = limit_config['max_requests']
        window_seconds = limit_config['window_seconds']
        
        now = time.time()
        key = f"{user_id}:{operation_type}"
        
        # Clean old entries
        self.rate_limit_store[key] = [
            timestamp for timestamp in self.rate_limit_store[key]
            if now - timestamp < window_seconds
        ]
        
        # Check limit
        if len(self.rate_limit_store[key]) >= max_requests:
            self.log_audit_event(
                'rate_limit_exceeded',
                user_id,
                {
                    'operation_type': operation_type,
                    'requests': len(self.rate_limit_store[key]),
                    'limit': max_requests,
                    'window_seconds': window_seconds
                }
            )
            return False, f"Rate limit exceeded. Maximum {max_requests} {operation_type} operations per {window_seconds} seconds."
        
        # Record this request
        self.rate_limit_store[key].append(now)
        
        return True, None
    
    def log_audit_event(
        self,
        event_type: str,
        user_id: str,
        details: Dict,
        severity: str = 'info'
    ):
        """
        Log security audit event.
        
        Args:
            event_type: Type of event (e.g., 'rate_limit_exceeded', 'prompt_injection_detected')
            user_id: User identifier
            details: Additional event details
            severity: Event severity ('info', 'warning', 'error', 'critical')
        """
        timestamp = datetime.utcnow().isoformat()
        
        log_entry = {
            'timestamp': timestamp,
            'event_type': event_type,
            'user_id': user_id,
            'severity': severity,
            'details': details
        }
        
        # Log to console
        log_message = f"[AUDIT] {event_type} | user={user_id} | {details}"
        if severity == 'critical' or severity == 'error':
            self.logger.error(log_message)
        elif severity == 'warning':
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        
        # Write to audit log file (daily rotation)
        today = datetime.utcnow().date()
        log_file = self.audit_log_dir / f"audit_{today.isoformat()}.jsonl"
        
        try:
            import json
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to write audit log: {e}")
    
    def sanitize_content_for_logging(self, content: str, max_length: int = 100) -> str:
        """
        Sanitize content for safe logging (remove sensitive data).
        
        Args:
            content: Content to sanitize
            max_length: Maximum length to log
            
        Returns:
            Sanitized content preview
        """
        if not content:
            return ""
        
        # Remove potential sensitive patterns
        sanitized = re.sub(r'(?i)(password|api[_\s]?key|secret|token|credential)\s*[:=]\s*\S+', 
                          r'\1=***REDACTED***', content)
        
        # Truncate
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."
        
        return sanitized
    
    def get_security_warning_for_content(self, content: str) -> Optional[str]:
        """
        Get a security warning message if content contains suspicious patterns.
        
        Args:
            content: Content to check
            
        Returns:
            Warning message or None
        """
        is_injection, patterns = self.detect_prompt_injection(content)
        
        if is_injection:
            return (
                "⚠️ SECURITY WARNING: This content contains patterns that may be "
                "attempting to inject instructions. Please review carefully before proceeding."
            )
        
        return None

