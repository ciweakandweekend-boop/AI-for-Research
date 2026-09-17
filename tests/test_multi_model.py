"""Offline regression tests. All API transports are mocked; no keys are needed."""
import copy
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import requests
import yaml

from src.agents import Agent, Laboratory
from src.config import LabConfig
from src.llm_client import LLMClient, LLMError
from src.main import run_lab, display_cost_estimate
from src.utils.output_logger import SessionOutputLogger


ROOT = Path(__file__).resolve().parents[1]


def chat_response(text="Mock evidence response.", status=200, finish_reason="stop"):
    return Mock(status_code=status, json=Mock(return_value={
        "choices": [{"message": {"content": text, "reasoning_content": "private reasoning",
                                 "reasoning": "private reasoning"},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 9},
    }))


class MultiModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.post = patch('src.llm_client.requests.post').start()
        self.anthropic = patch('src.llm_client.Anthropic').start()
        self.addCleanup(patch.stopall)
        self.post.return_value = chat_response()
        self.anthropic.return_value.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type='thinking', thinking='private reasoning'),
                     SimpleNamespace(type='text', text='Mock evidence response.')],
            usage=SimpleNamespace(input_tokens=17, output_tokens=9), stop_reason='end_turn',
        )
        self.data = yaml.safe_load((ROOT / 'config.yaml.example').read_text(encoding='utf-8'))
        self.data['anthropic_api_key'] = 'test-claude-key'
        self.data['api_keys'] = {k: f'test-{k}-key' for k in ('groq', 'qwen', 'zhipu', 'gemini')}
        Agent.TOKENS_IN.clear()
        Agent.TOKENS_OUT.clear()

    def config(self, data=None):
        path = Path(self.tmp.name) / 'config.yaml'
        path.write_text(yaml.safe_dump(self.data if data is None else data), encoding='utf-8')
        return LabConfig(str(path))

    def test_all_five_response_paths_use_each_agents_model_and_key(self):
        lab = Laboratory(self.config())
        self.assertEqual(len({a.model for a in lab.agents}), 5)
        expected_keys = ['groq', 'gemini', 'zhipu', 'anthropic', 'qwen']
        with patch('src.tools.web_search.ArxivSearch.search', return_value=[]):
            for agent, key in zip(lab.agents, expected_keys):
                with self.subTest(agent=agent.name):
                    agent.direct_messages['Colleague'] = [{'content': 'Review this evidence.'}]
                    calls = [
                        lambda: agent.generate_response([{'role': 'user', 'content': 'Discuss the evidence.'}]),
                        lambda: agent.generate_response_to_direct_message('Colleague'),
                        lambda: agent.process_document('Paper text', 'Analyze this paper.'),
                        lambda: agent.generate_response_with_research('EEG reasoning'),
                        lambda: agent.generate_response_with_specialized_prompt('Analyze this paper.'),
                    ]
                    for invoke in calls:
                        reply = invoke()
                        self.assertIn('Mock evidence response.', reply)
                        self.assertNotIn('private reasoning', reply)
                        if agent.provider == 'anthropic':
                            kwargs = self.anthropic.return_value.messages.create.call_args.kwargs
                            self.assertEqual(kwargs['model'], agent.model)
                        else:
                            args, kwargs = self.post.call_args
                            expected_base = {
                                'groq': 'https://api.groq.com/openai/v1',
                                'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                                'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
                                'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
                            }[key]
                            self.assertEqual(args[0], expected_base + '/chat/completions')
                            self.assertEqual(kwargs['headers']['Authorization'], f'Bearer test-{key}-key')
                            self.assertEqual(kwargs['json']['model'], agent.model)
                            token_field = 'max_completion_tokens' if key == 'groq' else 'max_tokens'
                            self.assertEqual(kwargs['json'][token_field], agent.max_tokens)
                            if key == 'groq':
                                self.assertNotIn('max_tokens', kwargs['json'])
                                self.assertEqual(kwargs['json']['reasoning_effort'], 'low')
                                self.assertFalse(kwargs['json']['include_reasoning'])
                            self.assertEqual(kwargs['json']['messages'][0]['role'], 'system')
                            self.assertFalse(kwargs['json']['stream'])
                            system_text = kwargs['json']['messages'][0]['content']
                            if key == 'gemini':
                                self.assertEqual(kwargs['json']['model'], 'gemini-3.8-flash')
                                self.assertEqual(kwargs['json']['reasoning_effort'], 'high')
                                self.assertIn('Check evidence, methodology, citations and overclaiming.', system_text)
                            elif key == 'zhipu':
                                self.assertEqual(kwargs['json']['model'], 'glm-4.7-flash')
                                self.assertEqual(kwargs['json']['thinking'], {'type': 'enabled'})
                                self.assertEqual(kwargs['json']['temperature'], 0.2)
                                self.assertIn('Identify unsupported claims, methodological weaknesses,', system_text)
                                self.assertIn('confounding variables, and missing evidence.', system_text)
                            else:
                                self.assertNotIn('AGENT-SPECIFIC INSTRUCTIONS:', system_text)
                            if key == 'qwen':
                                self.assertFalse(kwargs['json']['enable_thinking'])
                                self.assertFalse(kwargs['json']['preserve_thinking'])
                    self.assertEqual(Agent.TOKENS_IN[agent.model], 17 * 5)
                    self.assertEqual(Agent.TOKENS_OUT[agent.model], 9 * 5)
        self.assertEqual(self.post.call_count, 20)
        self.assertEqual(self.anthropic.return_value.messages.create.call_count, 5)
        self.assertEqual(self.anthropic.call_args.kwargs['api_key'], 'test-claude-key')
        # Shared context is still broadcast to every model-backed agent.
        lab.add_message(role='assistant', content='Shared finding.', sender='Lea')
        for agent in lab.agents:
            self.assertEqual(agent.conversation[-1]['content'], 'Shared finding.')

    def test_legacy_single_claude_configuration_still_works(self):
        data = {'user': {'name': 'Test'}, 'anthropic_api_key': 'legacy-test-key',
                'model': 'legacy-model', 'agents': [{'name': 'Ada', 'specialty': 'Computer Scientist'}]}
        lab = Laboratory(self.config(data))
        self.assertEqual(lab.agents[0].provider, 'anthropic')
        self.assertEqual(lab.agents[0].model, 'legacy-model')
        self.post.assert_not_called()

    def test_new_provider_environment_keys_and_overrides(self):
        self.data['api_keys'] = {}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'gemini-test-key',
                                    'ZHIPU_API_KEY': 'zhipu-test-key',
                                    'DASHSCOPE_API_KEY': 'qwen-test-key', 'GROQ_API_KEY': 'groq-test-key'}):
            config = self.config()
            self.assertFalse(config.missing_credentials())
            self.assertEqual(config.agent_settings(config.agents[1])['api_key'], 'gemini-test-key')
            self.assertEqual(config.agent_settings(config.agents[2])['api_key'], 'zhipu-test-key')
            self.assertEqual(config.agent_settings(config.agents[0])['api_key'], 'groq-test-key')
            with patch.dict(os.environ, {'QWEN_API_KEY': 'qwen-override'}):
                self.assertEqual(config.agent_settings(config.agents[4])['api_key'], 'qwen-override')

    def test_new_providers_do_not_fall_back_to_nvidia_credentials(self):
        for key in ('groq', 'gemini', 'zhipu'):
            self.data['api_keys'][key] = ''
        with patch.dict(os.environ, {'NVIDIA_API_KEY': 'nvidia-only-test-key'}):
            config = self.config()
            for i, key in enumerate(('groq', 'gemini', 'zhipu')):
                with self.subTest(provider=key):
                    agent = config.agents[i]
                    self.assertEqual(config.agent_settings(agent)['api_key'], '')
                    self.assertIn(f"{agent['name']}: fill api_keys.{key} / {key.upper()}_API_KEY",
                                  config.missing_credentials())

    def test_legacy_nvidia_config_still_resolves_shared_key(self):
        self.data['agents'] = [{'name': 'OldAgent', 'specialty': 'Researcher',
                               'provider': 'nvidia', 'model': 'legacy-model', 'api_key_name': 'glm'}]
        with patch.dict(os.environ, {'NVIDIA_API_KEY': 'legacy-shared-key'}):
            config = self.config()
            self.assertEqual(config.agent_settings(config.agents[0])['api_key'], 'legacy-shared-key')

    def test_missing_keys_stop_before_any_client_or_request(self):
        self.data['api_keys'] = {'groq': 'YOUR_GROQ_KEY_HERE'}
        config = self.config()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run_lab(config.config_path, check_config=True), 2)
            self.assertEqual(run_lab(config.config_path), 2)
        for slot in ('groq', 'qwen', 'zhipu', 'gemini'):
            self.assertIn(f'api_keys.{slot}', output.getvalue())
        self.assertNotIn('test-claude-key', output.getvalue())
        self.post.assert_not_called()
        self.anthropic.assert_not_called()

    def test_ready_config_starts_and_displays_all_model_assignments(self):
        config = self.config()
        output = io.StringIO()
        with redirect_stdout(output), patch('builtins.input', return_value='exit'):
            self.assertEqual(run_lab(config.config_path, check_config=True), 0)
            self.assertEqual(run_lab(config.config_path), 0)
        for agent in config.agents:
            self.assertIn(agent['model'], output.getvalue())
        self.assertNotIn('test-groq-key', output.getvalue())
        self.post.assert_not_called()
        self.anthropic.return_value.messages.create.assert_not_called()

    def test_one_failed_agent_does_not_stop_the_other_primary_responses(self):
        lab = Laboratory(self.config())
        lab.agents[0].client.create = Mock(side_effect=LLMError('groq/openai/gpt-oss-120b: HTTP 401. Check this agent\'s API key.'))
        for agent in lab.agents[1:]:
            agent.client.create = Mock(return_value=SimpleNamespace(
                content=[SimpleNamespace(text=f'{agent.name} response')]))
        with redirect_stdout(io.StringIO()):
            lab.user_message('Reply with one short sentence.')
        output = io.StringIO()
        with redirect_stdout(output):
            responses = lab.generate_responses(num_responses=5, enable_collaboration=False,
                                               show_conversation_map=False)
        self.assertNotIn('Lea', [name for name, _ in responses])
        self.assertGreaterEqual(len(responses), 4)
        self.assertIn('Continuing with the remaining agents.', output.getvalue())

    def test_config_uses_a_real_display_name(self):
        self.assertEqual(self.config().user_name, 'Sally')

    def test_default_terminal_log_uses_session_timestamp_name(self):
        logger = SessionOutputLogger()
        self.assertRegex(logger.path.name, r'^session_\d{8}_\d{6}\.txt$')
        self.assertEqual(logger.path.parent.name, 'outputs')

    def test_bad_config_rejected_without_printing_yaml_secrets(self):
        path = Path(self.tmp.name) / 'broken.yaml'
        path.write_text('api_keys: [test-secret-123', encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            LabConfig(str(path))
        self.assertNotIn('test-secret-123', str(ctx.exception))
        for updates in ({'provider': 'unknown'}, {'model': ''}, {'max_tokens': -1}, {'system_prompt': []},
                        {'base_url': 'https://user:password@example.com'},
                        {'extra_body': {'model': 'wrong-model'}},
                        {'extra_body': {'max_completion_tokens': 99999}}):
            with self.subTest(updates=updates):
                data = copy.deepcopy(self.data)
                data['agents'][0].update(updates)
                with self.assertRaises(ValueError):
                    self.config(data)

    def test_http_auth_errors_are_safe_and_not_retried(self):
        lab = Laboratory(self.config())
        self.post.return_value = chat_response(status=401)
        self.post.return_value.text = 'sensitive-server-body test-groq-key'
        with patch('src.agents.base.time.sleep') as sleep:
            with self.assertRaises(LLMError) as ctx:
                lab.agents[0].generate_response([{'role': 'user', 'content': 'hello'}])
        self.assertIn('HTTP 401', str(ctx.exception))
        self.assertNotIn('test-groq-key', str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)
        self.post.assert_called_once()
        sleep.assert_not_called()

    def test_reasoning_only_and_malformed_response_are_not_answers(self):
        client = LLMClient('test-key', provider='nvidia')
        for response in (chat_response(text=None, finish_reason='length'),
                         Mock(status_code=200, json=Mock(return_value={'choices': []})),
                         Mock(status_code=200, json=Mock(side_effect=ValueError('secret-body')))):
            with self.subTest(response=response):
                self.post.return_value = response
                with self.assertRaises(LLMError) as ctx:
                    client.create(model='test-model', system='system', messages=[{'role': 'user', 'content': 'hi'}])
                self.assertNotIn('secret-body', str(ctx.exception))

    def test_synthetic_followup_passes_current_message_to_recipient(self):
        lab = Laboratory(self.config())
        marie = lab.get_agent_by_name('Marie')
        marie.client.create = Mock(return_value=SimpleNamespace(
            content=[SimpleNamespace(text='Marie follow-up response')]))

        response = marie.generate_response_to_direct_message(
            'Lea',
            context='Discuss the current technical topic.',
            message_content='Lea asks Marie to assess the method.'
        )

        self.assertTrue(response.startswith('Marie follow-up response'))
        self.assertNotIn('Lea', marie.direct_messages)
        request = marie.client.create.call_args.kwargs
        self.assertIn('Lea asks Marie to assess the method.', request['messages'][0]['content'])

    def test_provider_503_is_retryable_and_records_status_without_body(self):
        client = LLMClient('test-key', provider='gemini')
        self.post.return_value = chat_response(status=503)

        with self.assertRaises(LLMError) as ctx:
            client.create(model='gemini-3.8-flash', system='system', messages=[{'role': 'user', 'content': 'hi'}])

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertTrue(ctx.exception.retryable)
        self.assertNotIn('test-key', str(ctx.exception))

    def test_agent_retries_transient_503_before_reporting_unavailable(self):
        lab = Laboratory(self.config())
        self.post.return_value = chat_response(status=503)
        output = io.StringIO()

        with patch('src.agents.base.time.sleep') as sleep, redirect_stdout(output):
            with self.assertRaises(LLMError):
                lab.get_agent_by_name('Emmy').generate_response(
                    [{'role': 'user', 'content': 'Reply with one short sentence.'}]
                )

        self.assertEqual(self.post.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertIn('returned HTTP 503; retrying 1/5', output.getvalue())

    def test_timeout_is_retryable_and_does_not_leak_transport_details(self):
        self.post.side_effect = requests.Timeout('Authorization: Bearer test-secret')
        with self.assertRaises(LLMError) as ctx:
            LLMClient('test-key', 'nvidia').create(model='test-model', system='s', messages=[])
        self.assertTrue(ctx.exception.retryable)
        self.assertNotIn('test-secret', str(ctx.exception))

    def test_normalization_does_not_mutate_shared_messages(self):
        messages = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'earlier answer'}]
        original = copy.deepcopy(messages)
        self.post.return_value = chat_response(text=[{'type': 'text', 'text': 'answer'}])
        reply = LLMClient('test-key', 'nvidia').create(model='test-model', system='s', messages=messages)
        self.assertEqual(reply.content[0].text, 'answer')
        self.assertEqual(messages, original)
        self.assertEqual(self.post.call_args.kwargs['json']['messages'][-1]['role'], 'user')

    def test_unpriced_models_are_not_assigned_invented_costs(self):
        lab = Laboratory(self.config())
        output = io.StringIO()
        with redirect_stdout(output):
            display_cost_estimate(lab)
        self.assertIn('Total cost unavailable', output.getvalue())
        self.assertNotIn('$0.0000', output.getvalue())


if __name__ == '__main__':
    unittest.main()
