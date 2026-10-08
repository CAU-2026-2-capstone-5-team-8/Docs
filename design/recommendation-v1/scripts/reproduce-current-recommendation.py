"""Run an explicit frozen ML checkout on real book facts and synthetic observations.

No service, catalog, learner record, model setting, or raw book text is modified.
Run with the pinned ML checkout on PYTHONPATH and its existing environment.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from bookmatch_ml.concept_v2.learning_fit import LearningFitRequest, recommend_learning
from bookmatch_ml.config import load_ranking_v2_config

PIN = "88b0177bbf4f8549c5eca8c7b2f85a5f8a19ffb6"
SOURCE_HASH = "8082913b20d5f7664f2ee5e3e5c6901f8c9c69c03e82a32231d14d72c2849bc3"
CANDIDATE_HASH = "sha256:0c987d0d7ce587436c41915c9fa79e0ac888de670dcd93b6066a555ff399e35c"
METADATA_HASH = "sha256:2ca7e8df020ebf139f64a13c9733e0de16868ea104908a1d5bba9003e51857d0"
CONCEPTS = ["matrix", "vector", "linear system", "linear independence", "basis", "orthogonality"]


def digest(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def source_digest(root):
    result = hashlib.sha256()
    paths = sorted([*root.glob("src/**/*.py"),
                    *(p for p in (root / "configs").rglob("*") if p.is_file())])
    for path in paths:
        result.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return result.hexdigest()


def key_without_id(item):
    return (
        {"ready-to-explore": 0, "check-first": 1, "foundation-gap": 2}[item["status"]],
        item["reviewOnly"],
        item["foundationStatus"] == "not-established",
        item["practiceConceptCount"] == 0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ml-root", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--books", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.ml_root.resolve()
    if source_digest(root) != SOURCE_HASH:
        raise ValueError("ML source/config tree does not match the pinned commit")
    if digest(args.candidates) != CANDIDATE_HASH or digest(args.books) != METADATA_HASH:
        raise ValueError("Inputs do not match the pinned historical snapshot")
    # Verify the code loaded by PYTHONPATH is the explicitly selected checkout.
    import bookmatch_ml.concept_v2.learning_fit as implementation
    if Path(implementation.__file__).resolve() != root / "src/bookmatch_ml/concept_v2/learning_fit.py":
        raise ValueError("PYTHONPATH does not select --ml-root")
    source = root / "src/bookmatch_ml/concept_v2/learning_fit.py"
    candidates = read_rows(args.candidates)
    books = {row["book_id"]: row for row in read_rows(args.books)}
    if len({row['book_id'] for row in candidates}) != len(candidates):
        raise ValueError("duplicate candidates")
    if any(row['book_id'] not in books for row in candidates):
        raise ValueError("candidate metadata missing")
    config = load_ranking_v2_config(root / "configs/ranking_v2.yaml")
    candidate_hash = digest(args.candidates)
    wire_books = [{
        "bookId": row["book_id"],
        "coveredConcepts": [c["concept"] for c in row["covered_concepts"]],
        "sourceArtifactVersion": "discovery-catalog-live-20260929-v1",
        "sourceArtifactHash": candidate_hash,
    } for row in candidates]
    report = {
        "runDate": "2026-10-05",
        "mlCommit": PIN,
        "sourceAndConfigHash": "sha256:" + SOURCE_HASH,
        "calculationFileHash": digest(source),
        "candidateHash": candidate_hash,
        "metadataHash": digest(args.books),
        "snapshotDate": "2026-09-29",
        "readerEvidence": "synthetic_scenarios_not_real_users_or_assessment_sessions",
        "accuracyMeasured": False,
        "path": "offline_call_to_current_recommend_learning_not_browser_or_database",
        "evidenceReferences": "legacy_candidates_without_enriched_source_references",
        "candidateCount": len(candidates),
        "scenarios": [],
    }
    labels = [("unmeasured", "응답 없음", None),
              ("all_six_incorrect", "6개 개념 적용 문항에서 각각 오답을 가정", 0),
              ("all_six_correct", "6개 개념 적용 문항에서 각각 정답을 가정", 1)]
    complete_results = {}
    for name, label, correct in labels:
        observations = [] if correct is None else [{
            "conceptId": concept, "ability": "application",
            "responseCount": 1, "correctCount": correct,
        } for concept in CONCEPTS]
        base = {"modelVersion": "concept-learning-v2", "topicId": "linear-algebra",
                "ability": "application", "observations": observations,
                "candidateBooks": wire_books}
        top = recommend_learning(LearningFitRequest.model_validate({**base, "limit": 5}), config)
        # This historical snapshot has 11 mapped candidates, so 20 reveals all ties.
        full = recommend_learning(LearningFitRequest.model_validate({**base, "limit": 20}), config)
        if full["mappedCandidateCount"] > 20:
            raise ValueError("Use an all-candidate audit before reporting tie counts above 20")
        ties = Counter(key_without_id(item) for item in full["items"])
        result = {
            "name": name, "label": label, "observations": observations,
            "mappedCandidateCount": top["mappedCandidateCount"],
            "unmappedCandidateCount": top["unmappedCandidateCount"],
            "graphHash": top["graphHash"], "configHash": top["configHash"],
            "allMappedStatusCounts": dict(Counter(item["status"] for item in full["items"])),
            "items": [{
                "rank": item["rank"], "bookId": item["bookId"],
                "title": books[item["bookId"]]["title"],
                "status": item["status"], "reviewOnly": item["reviewOnly"],
                "practiceConceptCount": item["practiceConceptCount"],
                "unmeasuredConceptCount": item["unmeasuredConceptCount"],
                "sameSortCriteriaCandidateCount": ties[key_without_id(item)],
                "reasons": item["reasons"],
            } for item in top["items"]],
        }
        report["scenarios"].append(result)
        complete_results[name] = {"request": {**base, "limit": 5}, "response": top}
    report["sameTopFiveAcrossAllScenarios"] = len({
        tuple(item['bookId'] for item in row['items']) for row in report['scenarios']
    }) == 1
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "requests-and-results.json").write_text(json.dumps(complete_results, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 현재 추천 계산 재현 — 2026-10-05", "",
        "**실도서의 과거 수집 snapshot + 가상 응답 + 현재 ML 코드의 오프라인 계산**이다.",
        "실제 사용자 실험·현재 실행 DB·브라우저 전체 경로·추천 정확도 검증이 아니다.", "",
        f"- ML 코드: `{PIN}` (`concept-learning-v2`).",
        f"- 2026-09-29 선형대수 후보 {len(candidates)}권. 개념 매칭 {top['mappedCandidateCount']}권, 미매칭 {top['unmappedCandidateCount']}권.",
        "- 같은 6개 개념의 application 응답을 바꾼 경계 사례. 현재 9문항 발급 세션을 재현한 것은 아니다.",
        "- 역사적 입력에는 새 본문 요구사항/근거 URL이 없어 추가한 것처럼 표시하지 않는다.",
        "- 풀이집 등 도서 유형을 이번 계산에서 새로 선별하지 않았다.", ""]
    names = {"ready-to-explore": "다음 배움 후보", "check-first": "선수개념 확인 필요", "foundation-gap": "기초 복습부터"}
    for scenario in report['scenarios']:
        lines += [f"## {scenario['label']}", "", "| 순서 | 실제 수집 제목 | 준비도 범주 | 같은 정렬 조건 후보 수 |", "| --- | --- | --- | --- |"]
        for item in scenario['items']:
            title = item['title'].replace('|', '\\|').replace('\n', ' ')
            lines.append(f"| {item['rank']} | {title} | {names[item['status']]} | {item['sameSortCriteriaCandidateCount']} |")
        lines += ["", "같은 정렬 조건 후보 수는 해당 추천과 ID를 제외한 정렬 조건이 모두 같은 후보의 수다.", ""]
    lines += ["## 해석", "",
        f"세 시나리오의 Top-5 순서가 모두 같은가: **{'예' if report['sameTopFiveAcrossAllScenarios'] else '아니오'}**.",
        "준비도 범주 변화와 순위 변화를 따로 살펴야 한다. 같은 범주의 동률은 도서 ID로 결정되며 적합성 우열의 증거가 아니다.",
        "정답을 가정한 6개 개념 밖의 선수개념은 여전히 미평가다. 이 결과를 완전한 숙달 판정으로 해석하지 않는다.",
        "현재의 규칙과 데이터 한계를 관찰한 사례이며, 새 설계가 더 좋다는 증거도 아니다.", "",
        "특히 오답 시나리오의 상위 5권은 모두 같은 정렬 조건이다. 다른 6권에서 선수개념 오답이 관찰돼",
        "foundation-gap으로 내려간 반면 이 5권은 check-first로 남아 위에 놓였다. 이 결과만으로",
        "상위 5권이 더 쉽거나 부족한 개념을 더 잘 가르친다고 말할 수 없다.", "",
        "## 재현", "",
        "스크립트는 명시적 ML checkout, candidate JSONL, book JSONL을 읽고 새 출력 폴더에만 쓴다.",
        "ML `88b0177`의 src와 configs를 사용한다. 원본 도서 입력은 기존 ignored 로컬 산출물이라 fresh clone에는 없다.",
        "입력 hash는 [집계 JSON](current-recommendation-summary.json)에 기록했다. 다른 입력을 같은 snapshot이라고 취급하지 않는다.", "",
        "```sh",
        "PYTHONPATH=/absolute/pinned-ML/src /absolute/ML/.venv/bin/python \\",
        "  scripts/reproduce-current-recommendation.py \\",
        "  --ml-root /absolute/pinned-ML \\",
        "  --candidates /absolute/discovery-catalog-live-v1/linear-algebra-candidates.jsonl \\",
        "  --books /absolute/discovery-catalog-live-v1/linear-algebra-books.jsonl \\",
        "  --output-dir /absolute/new-private-output",
        "```", "",
        "`scripts/` 경로는 이 설계 묶음 루트 기준이다. 원시 요청/응답은 private output에만 저장한다.",
        "공개 문서에는 원문 본문이나 참가자 정보가 없는 집계만 옮긴다."]
    (args.output_dir / 'current-recommendation.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({"candidateCount": report['candidateCount'],
                      "sameTopFiveAcrossAllScenarios": report['sameTopFiveAcrossAllScenarios'],
                      "scenarios": [{"name": s['name'], "status": s['allMappedStatusCounts'],
                                     "topFiveIds": [i['bookId'] for i in s['items']]} for s in report['scenarios']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
