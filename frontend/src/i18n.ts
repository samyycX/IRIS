import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  zh: {
    translation: {
      "IRIS Project": "I.R.I.S. 项目",
      "Home": "首页",
      "Create Task": "创建采集任务",
      "Task Type": "输入类型",
      "URL": "URL",
      "URL Placeholder": "https://wiki.example.com/page",
      "Instruction": "自由文本指令",
      "Instruction Placeholder": "例如：整理某实体相关资料并更新实体关系",
      "Entity Name": "实体名称",
      "Entity Placeholder": "例如：某实体名称",
      "Max Depth": "最大递归深度",
      "Max Pages": "最大页面数",
      "Concurrency": "单任务并行度",
      "Filter URLs": "筛选待选 URL",
      "Submit": "提交任务",
      "Task History": "历史任务",
      "Job ID": "Job ID",
      "Type": "类型",
      "Seed": "种子",
      "Status": "状态",
      "Visited": "访问页面",
      "Failed": "失败数",
      "No tasks": "暂无任务。",
      "Logs": "日志",
      "Job Detail": "任务详情",
      "Back to Home": "返回首页"
    }
  },
  en: {
    translation: {
      "IRIS Project": "I.R.I.S. Project",
      "Home": "Home",
      "Create Task": "Create Task",
      "Task Type": "Input Type",
      "URL": "URL",
      "URL Placeholder": "https://wiki.example.com/page",
      "Instruction": "Instruction",
      "Instruction Placeholder": "e.g., Extract info and update relations",
      "Entity Name": "Entity Name",
      "Entity Placeholder": "e.g., Entity name",
      "Max Depth": "Max Depth",
      "Max Pages": "Max Pages",
      "Concurrency": "Concurrency",
      "Filter URLs": "Filter Candidate URLs",
      "Submit": "Submit Task",
      "Task History": "Task History",
      "Job ID": "Job ID",
      "Type": "Type",
      "Seed": "Seed",
      "Status": "Status",
      "Visited": "Visited Pages",
      "Failed": "Failed Count",
      "No tasks": "No tasks yet.",
      "Logs": "Logs",
      "Job Detail": "Job Detail",
      "Back to Home": "Back to Home"
    }
  }
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: "zh",
    fallbackLng: "en",
    interpolation: {
      escapeValue: false
    }
  });

export default i18n;