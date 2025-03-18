#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OpenAI API提供者
实现大语言模型提供者接口，提供OpenAI兼容的API服务
"""

import os
import json
import logging
import requests
import re
from typing import Dict, Any, List, Optional, Union, Generator

from src.interfaces.llm_provider import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI API提供者"""
    
    def __init__(self, api_config, logger=None):
        """初始化API客户端"""
        self.api_key = api_config.api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = api_config.base_url
        self.model = api_config.model
        self.timeout = api_config.timeout
        
        self.logger = logger or logging.getLogger("openai_provider")
        
        # 系统提示模板
        self.system_prompt_template = {
            "command": """你是一个专业的Linux命令助手，帮助用户将自然语言需求转换为Linux命令。
请根据用户的描述生成最合适的Linux命令，并提供简洁的解释。
只输出一条命令，除非任务必须分步骤完成。
不要提供无关的解释或教程。
如果命令可能有危险（如rm -rf），请标记并警告。

按以下JSON格式返回：
{
    "command": "实际的Linux命令",
    "explanation": "对命令的简要解释",
    "dangerous": true/false,
    "reason_if_dangerous": "如果命令危险，说明原因"
}""",
            "analyze": """你是一个专业的Linux系统管理员助手。
你的任务是分析Linux命令的输出，并以清晰、专业的方式解释结果。
如果遇到错误，请分析错误原因，并提供修复建议。

返回JSON格式如下：
{
    "explanation": "对结果的主要解释",
    "recommendations": ["建议1", "建议2", ...],
    "next_steps": [
        {"command": "可能的下一步命令", "explanation": "解释"},
        ...
    ]
}"""
        }
    
    def is_available(self) -> bool:
        """检查API是否可用"""
        if not self.api_key:
            self.logger.warning("未设置API密钥")
            return False
        
        try:
            headers = self._build_headers()
            url = f"{self.base_url}/models"
            
            response = requests.get(
                url,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                self.logger.info("OpenAI API连接成功")
                return True
            else:
                self.logger.warning(f"API连接测试失败: {response.status_code} {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"API连接测试异常: {e}")
            return False
    
    def _build_headers(self) -> Dict[str, str]:
        """构建请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
    
    def _handle_api_error(self, response: requests.Response) -> Dict[str, Any]:
        """处理API错误响应"""
        try:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", f"API错误: {response.status_code}")
            self.logger.error(f"API错误: {error_msg}")
            return {"error": error_msg}
        except json.JSONDecodeError:
            error_msg = f"API返回错误 ({response.status_code}): {response.text}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"处理API错误时发生异常: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
    
    def _call_openai_api(self, messages: List[Dict[str, str]], 
                         temperature: float = 0.7,
                         max_tokens: int = 4000,
                         stream: bool = False) -> Union[Dict[str, Any], Generator[str, None, None]]:
        """调用OpenAI API"""
        self.logger.info(f"调用OpenAI API: {self.model}")
        
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        try:
            if stream:
                return self._stream_response(url, headers, data)
            else:
                response = requests.post(
                    url,
                    headers=headers,
                    json=data,
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    return self._handle_api_error(response)
        except requests.RequestException as e:
            error_msg = f"API请求失败: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"调用API时发生异常: {e}"
            self.logger.error(error_msg)
            return {"error": error_msg}
    
    def _stream_response(self, url: str, headers: Dict[str, str], data: Dict[str, Any]) -> Generator[str, None, None]:
        """流式获取API响应"""
        try:
            self.logger.info(f"开始流式获取响应，URL: {url}")
            with requests.post(url, headers=headers, json=data, stream=True, timeout=self.timeout) as response:
                if response.status_code != 200:
                    error_msg = f"错误: API返回 {response.status_code}"
                    self.logger.error(error_msg)
                    yield error_msg
                    return
                
                self.logger.info("流式响应连接成功，开始接收数据")
                buffer = ""
                chunk_count = 0
                for chunk in response.iter_lines():
                    if chunk:
                        chunk_str = chunk.decode('utf-8')
                        if chunk_str.startswith('data: '):
                            json_str = chunk_str[6:].strip()
                            if json_str == "[DONE]":
                                self.logger.info("流式响应接收完毕")
                                break
                            
                            try:
                                chunk_data = json.loads(json_str)
                                if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                    content = chunk_data['choices'][0].get('delta', {}).get('content', '')
                                    if content:
                                        buffer += content
                                        chunk_count += 1
                                        if chunk_count % 10 == 0:
                                            self.logger.debug(f"已接收 {chunk_count} 个块")
                                        yield content
                            except json.JSONDecodeError:
                                self.logger.warning(f"无法解析流式响应: {json_str}")
                
                self.logger.info(f"流式响应结束，共接收 {chunk_count} 个数据块")
        except Exception as e:
            error_msg = f"流式获取响应失败: {e}"
            self.logger.error(error_msg)
            yield error_msg
    
    def _build_command_prompt(self, task: str, system_info: Dict[str, Any]) -> str:
        """构建命令生成的提示"""
        system_info_formatted = "\n".join([f"{k}: {v}" for k, v in system_info.items()])
        
        return (
            f"任务: {task}\n\n"
            f"系统信息:\n"
            f"{system_info_formatted}\n\n"
            f"请提供执行此任务的Linux命令。请确保命令安全且适合当前系统环境。"
            f"在返回结果中，请包含命令本身、解释执行目的以及是否是危险命令(如修改系统配置/数据删除/权限更改等)"
        )
    
    def _build_analysis_prompt(self, command: str, stdout: str, stderr: str) -> str:
        """构建命令分析的提示"""
        return (
            f"我执行了命令: {command}\n\n"
            f"标准输出:\n{stdout}\n\n"
            f"标准错误:\n{stderr}\n\n"
            f"请分析执行结果，解释输出含义，并提供下一步建议。"
            f"如果命令执行失败，请解释可能的原因并给出修复建议。"
        )
    
    def generate_command(self, task: str, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """获取执行任务的命令"""
        self.logger.info(f"获取命令，任务: {task}")
        
        prompt = self._build_command_prompt(task, system_info)
        messages = [
            {"role": "system", "content": self.system_prompt_template["command"]},
            {"role": "user", "content": prompt}
        ]
        
        response = self._call_openai_api(messages)
        
        if "error" in response:
            self.logger.error(f"命令API调用失败: {response['error']}")
            return {}
        
        try:
            content = response['choices'][0]['message']['content']
            
            try:
                # 尝试解析JSON
                result = json.loads(content)
                
                # 验证JSON包含必要字段
                if "command" in result:
                    self.logger.info(f"成功解析命令JSON: {result['command']}")
                    return result
                else:
                    self.logger.warning("JSON缺少必要字段")
                    return self._parse_text_response(content)
                    
            except json.JSONDecodeError:
                self.logger.warning("响应不是有效的JSON，尝试文本解析")
                return self._parse_text_response(content)
                
        except KeyError as e:
            self.logger.error(f"解析API回复失败: {e}")
            return {}
    
    def _parse_text_response(self, text: str) -> Dict[str, Any]:
        """解析文本格式的回复为结构化数据"""
        result = {}
        
        # 尝试从代码块中提取命令
        command_pattern = r"```(?:bash|shell)?\s*\n(.*?)\n```"
        command_match = re.search(command_pattern, text, re.DOTALL)
        if command_match:
            command_lines = command_match.group(1).strip().split('\n')
            for line in command_lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('//'):
                    result["command"] = line
                    break
            if "command" not in result:
                result["command"] = command_lines[0].strip()
        else:
            # 尝试从文本中提取命令
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith("命令:") or line.startswith("Command:"):
                    result["command"] = line.split(':', 1)[1].strip()
                    break
            
            # 如果仍未找到命令，尝试通过常见命令前缀识别
            if "command" not in result:
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        common_prefixes = ["sudo", "apt", "yum", "dnf", "pacman", "ls", "cp", "mv", "mkdir", "grep", "find"]
                        for prefix in common_prefixes:
                            if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] == ' '):
                                result["command"] = line
                                break
                        if "command" in result:
                            break
        
        # 提取解释
        explanation_pattern = r"(?:解释|说明|Explanation|Purpose)[:：]\s*(.*?)(?:\n\n|\n#|$)"
        explanation_match = re.search(explanation_pattern, text, re.DOTALL)
        if explanation_match:
            result["explanation"] = explanation_match.group(1).strip()
        else:
            # 简单假设第一个非命令、非空行是解释
            for line in text.split('\n'):
                line = line.strip()
                if line and ("command" not in result or line != result["command"]):
                    result["explanation"] = line
                    break
        
        # 判断是否危险
        dangerous_pattern = r"(?:危险|是否危险|Dangerous)[:：]\s*(.*?)(?:\n|$)"
        dangerous_match = re.search(dangerous_pattern, text, re.DOTALL)
        if dangerous_match:
            danger_text = dangerous_match.group(1).lower()
            result["dangerous"] = "是" in danger_text or "yes" in danger_text or "true" in danger_text
            
            # 提取危险原因
            if result.get("dangerous"):
                reason_pattern = r"(?:原因|理由|Reason)[:：]\s*(.*?)(?:\n\n|\n#|$)"
                reason_match = re.search(reason_pattern, text, re.DOTALL)
                if reason_match:
                    result["reason_if_dangerous"] = reason_match.group(1).strip()
                else:
                    result["reason_if_dangerous"] = "未提供具体风险原因"
        else:
            # 默认为安全
            result["dangerous"] = False
        
        # 确保所有必要字段都存在
        if "command" not in result or not result["command"]:
            result["command"] = "echo 'Unable to generate a proper command'"
            
        if "explanation" not in result:
            result["explanation"] = "执行所请求的任务"
            
        return result
    
    def analyze_output(self, command: str, stdout: str, stderr: str) -> Dict[str, Any]:
        """分析命令执行结果"""
        self.logger.info(f"分析命令执行结果: {command}")
        
        messages = [
            {"role": "system", "content": self.system_prompt_template["analyze"]},
            {"role": "user", "content": self._build_analysis_prompt(command, stdout, stderr)}
        ]
        
        response = self._call_openai_api(messages)
        
        if "error" in response:
            self.logger.error(f"分析API调用失败: {response['error']}")
            return {"explanation": f"无法分析执行结果: {response['error']}"}
        
        try:
            content = response['choices'][0]['message']['content']
            
            try:
                # 尝试解析为JSON格式
                result = json.loads(content)
                if "explanation" in result:
                    return result
                else:
                    return {"explanation": content}
            except json.JSONDecodeError:
                # 如果不是JSON，则作为纯文本返回
                return {"explanation": content}
        except KeyError as e:
            self.logger.error(f"解析API回复失败: {e}")
            return {"explanation": "抱歉，无法分析命令执行结果"}
    
    def get_template_suggestion(self, prompt: str, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """获取模板建议"""
        self.logger.info(f"获取模板建议: {prompt}")
        
        system_info_formatted = "\n".join([f"{k}: {v}" for k, v in system_info.items()])
        full_prompt = (
            f"{prompt}\n\n"
            f"系统信息:\n"
            f"{system_info_formatted}\n\n"
            f"请提供简洁明了的编辑建议和语法提示，让用户可以有效完成编辑工作。"
        )
        
        messages = [
            {"role": "user", "content": full_prompt}
        ]
        
        response = self._call_openai_api(messages)
        
        if "error" in response:
            self.logger.error(f"模板API调用失败: {response['error']}")
            return {"suggestion": f"无法获取建议: {response['error']}"}
        
        try:
            content = response['choices'][0]['message']['content']
            return {"suggestion": content}
        except KeyError as e:
            self.logger.error(f"解析API回复失败: {e}")
            return {"suggestion": "抱歉，无法获取模板建议"}
    
    def stream_response(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        """流式获取响应"""
        self.logger.info("流式获取响应")
        
        response_generator = self._call_openai_api(messages, stream=True)
        
        if isinstance(response_generator, dict) and "error" in response_generator:
            yield f"错误: {response_generator['error']}"
            return
        
        if isinstance(response_generator, Generator):
            yield from response_generator
        else:
            self.logger.error("无法获取流式响应")
            yield "无法获取流式响应" 