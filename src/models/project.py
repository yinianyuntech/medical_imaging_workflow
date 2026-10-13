from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
import uuid


@dataclass
class Project:
    """项目数据模型"""
    project_id: str
    name: str
    description: str = ""
    created_at: datetime = None
    updated_at: datetime = None
    status: str = "active"  # active, archived, deleted
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """初始化后处理"""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        if self.metadata is None:
            self.metadata = {}
    
    @classmethod
    def create_new(cls, name: str, description: str = "") -> 'Project':
        """创建新项目"""
        project_id = str(uuid.uuid4())
        return cls(
            project_id=project_id,
            name=name,
            description=description
        )
    
    def update_info(self, name: str = None, description: str = None, metadata: Dict[str, Any] = None):
        """更新项目信息"""
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if metadata is not None:
            self.metadata.update(metadata)
        self.updated_at = datetime.now()
    
    def archive(self):
        """归档项目"""
        self.status = "archived"
        self.updated_at = datetime.now()
    
    def activate(self):
        """激活项目"""
        self.status = "active"
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'project_id': self.project_id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'status': self.status,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """从字典创建项目对象"""
        created_at = None
        updated_at = None
        
        if data.get('created_at'):
            created_at = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at'):
            updated_at = datetime.fromisoformat(data['updated_at'])
        
        return cls(
            project_id=data['project_id'],
            name=data['name'],
            description=data.get('description', ''),
            created_at=created_at,
            updated_at=updated_at,
            status=data.get('status', 'active'),
            metadata=data.get('metadata', {})
        )