import json
import os
from typing import Any, Dict, List, Optional

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None


class LocalCollection:
    def __init__(self) -> None:
        self._docs: List[Dict[str, Any]] = []

    def _matches(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = []
        for doc in self._docs:
            matched = True
            for key, value in query.items():
                if doc.get(key) != value:
                    matched = False
                    break
            if matched:
                result.append(doc)
        return result

    def count_documents(self, query: Dict[str, Any], limit: Optional[int] = None) -> int:
        matches = self._matches(query)
        if limit is not None:
            return min(len(matches), limit)
        return len(matches)

    def find(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
        documents = self._matches(query)
        if projection is None:
            return [doc.copy() for doc in documents]
        projected = []
        for doc in documents:
            projected.append({k: doc.get(k) for k, include in projection.items() if include and k in doc})
        return projected

    def update_one(self, filter: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> None:
        existing = self._matches(filter)
        if existing:
            doc = existing[0]
            if "$set" in update:
                for key, value in update["$set"].items():
                    doc[key] = value
            return

        if upsert:
            new_doc = filter.copy()
            if "$set" in update:
                new_doc.update(update["$set"])
            self._docs.append(new_doc)


class LocalDatabase:
    def __init__(self) -> None:
        self._collections: Dict[str, LocalCollection] = {}

    def __getitem__(self, name: str) -> LocalCollection:
        if name not in self._collections:
            self._collections[name] = LocalCollection()
        return self._collections[name]


class MongoDBHelper:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        mongo_db: Optional[str] = None,
        company_codes_path: Optional[str] = None,
    ) -> None:
        self.mongo_uri = mongo_uri or os.getenv("MONGODB_URI")
        self.mongo_db = mongo_db or os.getenv("MONGODB_DB", "stock_reports")
        self.company_codes_path = (
            company_codes_path
            or os.path.abspath("company_codes.json")
        )
        self.client = None
        self.db = None

        if self.mongo_uri:
            if MongoClient is None:
                raise ImportError(
                    "pymongo is required for MongoDB support. Install with 'pip install pymongo'."
                )
            self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            self.db = self.client[self.mongo_db]
        else:
            self.db = LocalDatabase()

    def get_all_company_codes(self) -> List[str]:
        if self.mongo_uri:
            collection = self.db["companies"]
            codes = set()
            for doc in collection.find({}, {"_id": 0, "code": 1, "公司代號": 1}):
                value = doc.get("code") or doc.get("公司代號")
                if value is not None:
                    codes.add(str(value).strip())
            return sorted(codes)

        return self._load_company_codes_from_file()

    def _load_company_codes_from_file(self) -> List[str]:
        if not os.path.exists(self.company_codes_path):
            raise FileNotFoundError(
                f"company_codes.json not found at {self.company_codes_path}. "
                "請提供 MONGODB_URI，或建立一個包含公司代號清單的 company_codes.json。"
            )

        with open(self.company_codes_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = data.get("company_codes", data.get("codes", []))

        if not isinstance(data, list):
            raise ValueError(
                "company_codes.json 必須是一個包含公司代號清單的 JSON 陣列，或包含 company_codes 欄位的物件。"
            )

        return sorted({str(item).strip() for item in data if item})

    def close(self) -> None:
        if self.client:
            self.client.close()
