
from transformers import AutoModel, AutoTokenizer
import time
import importlib
from toolbox import update_ui, get_conf
from multiprocessing import Process, Pipe

#################################################################################
class GetGLMHandle(Process):
    def __init__(self):
        super().__init__(daemon=True)
        self.parent, self.child = Pipe()
        self.chatglm_model = None
        self.chatglm_tokenizer = None
        self.start()
        print('初始化')
        
    def ready(self):
        return self.chatglm_model is not None

    def run(self):
        while True:
            try:
                if self.chatglm_model is None:
                    self.chatglm_tokenizer = AutoTokenizer.from_pretrained("THUDM/chatglm-6b", trust_remote_code=True)
                    device, = get_conf('LOCAL_MODEL_DEVICE')
                    if device=='cpu':
                        self.chatglm_model = AutoModel.from_pretrained("THUDM/chatglm-6b", trust_remote_code=True).float()
                    else:
                        self.chatglm_model = AutoModel.from_pretrained("THUDM/chatglm-6b", trust_remote_code=True).half().cuda()
                    self.chatglm_model = self.chatglm_model.eval()
                    break
                else:
                    break
            except:
                pass
        while True:
            kwargs = self.child.recv()
            try:
                for response, history in self.chatglm_model.stream_chat(self.chatglm_tokenizer, **kwargs):
                    self.child.send(response)
            except:
                self.child.send('[Local Message] Call ChatGLM fail.')
            self.child.send('[Finish]')

    def stream_chat(self, **kwargs):
        self.parent.send(kwargs)
        while True:
            res = self.parent.recv()
            if res != '[Finish]':
                yield res
            else:
                break
        return
    
global glm_handle
glm_handle = None
#################################################################################
def predict_no_ui_long_connection(inputs, llm_kwargs, history=[], sys_prompt="", observe_window=None, console_slience=False):
    """
        多线程方法
        函数的说明请见 request_llm/bridge_all.py
    """
    global glm_handle
    if glm_handle is None:
        glm_handle = GetGLMHandle()
        observe_window[0] = "ChatGLM尚未加载，加载需要一段时间。注意，取决于`config.py`的配置，ChatGLM消耗大量的内存（CPU）或显存（GPU），也许会导致低配计算机卡死 ……"

    # chatglm 没有 sys_prompt 接口，因此把prompt加入 history
    history_feedin = []
    for i in range(len(history)//2):
        history_feedin.append(["What can I do?", sys_prompt] )
        history_feedin.append([history[2*i], history[2*i+1]] )

    watch_dog_patience = 5 # 看门狗 (watchdog) 的耐心, 设置5秒即可
    response = ""
    for response in glm_handle.stream_chat(query=inputs, history=history_feedin, max_length=llm_kwargs['max_length'], top_p=llm_kwargs['top_p'], temperature=llm_kwargs['temperature']):
        observe_window[0] = response
        if len(observe_window) >= 2:  
            if (time.time()-observe_window[1]) > watch_dog_patience:
                raise RuntimeError("程序终止。")
    return response



def predict(inputs, llm_kwargs, plugin_kwargs, chatbot, history=[], system_prompt='', stream = True, additional_fn=None):
    """
        单线程方法
        函数的说明请见 request_llm/bridge_all.py
    """
    chatbot.append((inputs, ""))

    global glm_handle
    if glm_handle is None:
        glm_handle = GetGLMHandle()
        chatbot[-1] = (inputs, "ChatGLM尚未加载，加载需要一段时间。注意，取决于`config.py`的配置，ChatGLM消耗大量的内存（CPU）或显存（GPU），也许会导致低配计算机卡死 ……")
        yield from update_ui(chatbot=chatbot, history=[])

    if additional_fn is not None:
        import core_functional
        importlib.reload(core_functional)    # 热更新prompt
        core_functional = core_functional.get_core_functions()
        if "PreProcess" in core_functional[additional_fn]: inputs = core_functional[additional_fn]["PreProcess"](inputs)  # 获取预处理函数（如果有的话）
        inputs = core_functional[additional_fn]["Prefix"] + inputs + core_functional[additional_fn]["Suffix"]

    history_feedin = []
    for i in range(len(history)//2):
        history_feedin.append(["What can I do?", system_prompt] )
        history_feedin.append([history[2*i], history[2*i+1]] )

    for response in glm_handle.stream_chat(query=inputs, history=history_feedin, max_length=llm_kwargs['max_length'], top_p=llm_kwargs['top_p'], temperature=llm_kwargs['temperature']):
        chatbot[-1] = (inputs, response)
        yield from update_ui(chatbot=chatbot, history=history)