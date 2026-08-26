import pandas as pd
from app.config import COURSES_FILE

REQUIRED_COLUMNS = [
    "program", "subprogram", "course_title", "description", "urlslug",
    "min_qualification", "required_stream", "min_percentage", "duration",
    "mode", "interest_tags", "career_outcomes", "prerequisite_course",
]


class CourseStore:
    def __init__(self, path: str = COURSES_FILE):
        self.path = path
        self.df = self._load(path)

    def _load(self, path: str) -> pd.DataFrame:
        df = pd.read_excel(path, sheet_name=0)
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Course file is missing required columns: {missing}")
        df = df.fillna("")
        df["_tags"] = df["interest_tags"].apply(
            lambda s: [t.strip().lower() for t in str(s).split(",") if t.strip()]
        )
        return df

    def reload(self):
        self.df = self._load(self.path)

    def all_courses(self):
        return self.df.to_dict(orient="records")


course_store = CourseStore()