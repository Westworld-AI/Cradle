import atexit
from typing import Dict, Any

from cradle.utils.string_utils import replace_unsupported_chars
from cradle import constants
from cradle.log import Logger
from cradle.config import Config
from cradle.memory import LocalMemory
from cradle.provider import RestfulClaudeProvider
from cradle.provider import OpenAIProvider
from cradle.gameio.io_env import IOEnvironment
from cradle.gameio.game_manager import GameManager
from cradle.log.logger import process_log_messages
from cradle.provider import VideoRecordProvider
from cradle.provider import VideoClipProvider
from cradle.provider import InformationGatheringProvider
from cradle.provider import SelfReflectionProvider
from cradle.provider import TaskInferenceProvider
from cradle.provider import ActionPlanningProvider
from cradle.provider import SkillExecuteProvider
from cradle.environment import SubnauticaSkillRegistry,SubnauticaUIControl

config = Config()
logger = Logger()
memory = LocalMemory()
io_env = IOEnvironment()
video_record = VideoRecordProvider()

class PipelineRunner():

    def __init__(self,
                 llm_provider: Any,
                 embed_provider: Any,
                 task_description: str,
                 use_self_reflection: bool = False,
                 use_task_inference: bool = False):

        self.llm_provider = llm_provider
        self.embed_provider = embed_provider

        self.task_description = task_description
        self.use_self_reflection = use_self_reflection
        self.use_task_inference = use_task_inference

        # Init internal params
        self.set_internal_params()

    def set_internal_params(self, *args, **kwargs):

        self.provider_configs = config.provider_configs

        self.skill_registry = SubnauticaSkillRegistry(
            embedding_provider=self.embed_provider,
        )
        self.ui_control = SubnauticaUIControl()

        self.gm = GameManager(skill_registry=self.skill_registry, ui_control=self.ui_control)

        # Init skill library
        skills = self.gm.retrieve_skills(query_task=self.task_description,
                                         skill_num=config.skill_num,
                                         screen_type=constants.GENERAL_GAME_INTERFACE)
        self.skill_library = self.gm.get_skill_information(skills,
                                                           config.skill_library_with_code)

        # Init video provider
        self.video_clip = VideoClipProvider(gm=self.gm)

        # Init module providers
        self.information_gathering = InformationGatheringProvider(
            llm_provider=self.llm_provider,
            gm=self.gm,
            **self.provider_configs.information_gathering_provider
        )
        self.self_reflection = SelfReflectionProvider(
            llm_provider=self.llm_provider,
            gm=self.gm,
            **self.provider_configs.self_reflection_provider
        )
        self.task_inference = TaskInferenceProvider(
            llm_provider=self.llm_provider,
            gm=self.gm,
            **self.provider_configs.task_inference_provider
        )
        self.action_planning = ActionPlanningProvider(
            llm_provider=self.llm_provider,
            gm=self.gm,
            **self.provider_configs.action_planning_provider
        )

        # Init skill execute provider
        self.skill_execute = SkillExecuteProvider(gm=self.gm)

    def pipeline_shutdown(self):
        self.gm.cleanup_io()
        video_record.finish_capture()
        log = process_log_messages(config.work_dir)
        with open(config.work_dir + '/logs/log.md', 'w') as f:
            log = replace_unsupported_chars(log)
            f.write(log)
        logger.write('>>> Markdown generated.')
        logger.write('>>> Bye.')

    import time  # 导入time模块

    def run(self):

        # 1. Initiate the parameters
        success = False
        init_params = {
            "task_description": self.task_description,
            "skill_library": self.skill_library,
        }
        memory.update_info_history(init_params)

        # 2. Switch to game
        self.gm.switch_to_game()

        # 3. Start video recording
        video_record.start_capture()

        # 4. Initiate screen shot path and video clip path
        self.video_clip(init=True)

        # 6. Start the pipeline
        step = 0
        while not success:
            try:

                # 7.1. Information gathering
                self.run_information_gathering()

                step += 1

                if step > config.max_steps:
                    logger.write('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>  达到最大步数, 退出.')
                    break

            except KeyboardInterrupt:
                logger.write('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>  检测到键盘中断 Ctrl+C，退出。.')
                self.pipeline_shutdown()
                break

        self.pipeline_shutdown()

    def run_information_gathering(self):

        # 1. Get the video clip to information gathering
        self.video_clip(init=True)

        # 2. Execute the information gathering provider
        self.information_gathering()

    def run_self_reflection(self):

        # 1. Execute the self reflection provider
        self.self_reflection()

    # information summary and task inference
    def run_task_inference(self):

        # 1. Execute the task inference provider
        self.task_inference()
    def run_action_planning(self):

        # 1. Execute the action planning provider
        self.action_planning()

        # 2. Execute the skill execute provider
        self.skill_execute()

def exit_cleanup(runner):
    logger.write("Exiting pipeline.")
    runner.pipeline_shutdown()

def entry(args):
    task_description = config.task_description

    # Init LLM provider and embedding provider
    if "claude" in args.llmProviderConfig:
        llm_provider = RestfulClaudeProvider()
        llm_provider.init_provider(args.llmProviderConfig)
        logger.write(f"Claude do not support embedding, use OpenAI instead.")
        embed_provider = OpenAIProvider()
        embed_provider.init_provider(args.embedProviderConfig)
    else:  # OpenAI
        llm_provider = OpenAIProvider()
        llm_provider.init_provider(args.llmProviderConfig)
        embed_provider = llm_provider

    pipelineRunner = PipelineRunner(llm_provider,
                                    embed_provider,
                                    task_description=task_description,
                                    use_self_reflection=True,
                                    use_task_inference=True)

    atexit.register(exit_cleanup, pipelineRunner)

    pipelineRunner.run()