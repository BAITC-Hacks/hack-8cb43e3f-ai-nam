import os
import unittest
from unittest.mock import patch
from app import llm
from app.analysis import analyze
from app.parsers import parse_document


class LLMTests(unittest.TestCase):
    def result(self):
        old='1. Функции\n1.1. Организует проверку пожарной безопасности.\n1.2. Готовит бухгалтерскую отчетность.'
        new='1. Функции\n1.2. Готовит бухгалтерскую отчетность.'
        return analyze([parse_document(s.encode(),'doc.txt',side,side) for s,side in [(old,'before'),(new,'after')]])

    def test_model_cannot_introduce_fake_evidence(self):
        result=self.result();target=next(f for f in result['findings'] if f['kind']=='missing')
        answer=llm.Decisions(decisions=[llm.Decision(finding_id=target['id'],relation='equivalent',after_id='nonexistent',reason='unsupported',evidence_ids=['nonexistent'])])
        with patch.object(llm,'config',return_value={'available':True,'model':'test','local':True}),patch.object(llm,'request_model',return_value=answer):
            enriched=llm.enrich(result,lambda *_:None)
        self.assertEqual(enriched['ai']['reviewed'],0)
        self.assertEqual(target['kind'],'missing')

    def test_offline_ai_preserves_basic_result(self):
        result=self.result()
        with patch.object(llm,'config',return_value={'available':False}):llm.enrich(result,lambda *_:None)
        self.assertEqual(result['ai']['status'],'unavailable')
        self.assertTrue(any(f['kind']=='missing' for f in result['findings']))

    def test_valid_semantic_match_reconciles_matrix_and_counts(self):
        before='1. Функции\n1.1. Организует проверку информационной безопасности.'
        after='1. Функции\n1.1. Планирует и проводит аудит защиты информации.'
        result=analyze([parse_document(s.encode(),'doc.txt',side,side) for s,side in [(before,'before'),(after,'after')]])
        finding=next(f for f in result['findings'] if f['kind']=='missing')
        aid=result['documents'][1]['clauses'][1]['id']
        answer=llm.Decisions(decisions=[llm.Decision(finding_id=finding['id'],relation='changed',reason='Уточнены действия',evidence_ids=[finding['before_ids'][0],aid])])
        with patch.object(llm,'config',return_value={'available':True,'model':'test','local':True}),patch.object(llm,'request_model',return_value=answer):
            llm.enrich(result,lambda *_:None)
        self.assertEqual(result['ai']['reviewed'],1)
        self.assertEqual(result['stats']['matched'],1)
        self.assertEqual(result['stats']['coverage'],100)
        self.assertEqual(result['stats']['findings'],1)
        self.assertEqual(len(result['matrix']),1)
        self.assertEqual(result['findings'][0]['kind'],'modified')
