import type {Metadata} from "next";

export const metadata:Metadata={
  title:"Image Lab · 文生图工作台",
  description:"选择图片模型，输入提示词，生成并下载你的下一张画面。",
};

export default function ImageGeneratorLayout({children}:{children:React.ReactNode}){
  return children;
}
