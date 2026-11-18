import { test, expect } from "@playwright/test";

test("expired login preserves a draft for its owner and another account cannot load it", async ({ page }) => {
  let userId = "u", expired = false;
  const courses = [{id:"c",title:"课程",lessons:[{id:"L1",title:"会话测试课时"}]}];
  const view = () => ({userId,sessionId:`session-${userId}`,lessonId:"L1",phase:"discussion",
    stateVersion:1,contentGeneration:0,preparation:"ready",agentStage:"recall",courses,
    messages:[{role:"assistant",text:"请复述本课内容"}],browserCourseKey:`${userId}:c`,browserKey:`${userId}:c:L1`});
  const writes=[];
  await page.route("**/api/session/**", async route => {
    const path=new URL(route.request().url()).pathname;
    if (expired) return route.fulfill({status:401,json:{code:"SESSION_EXPIRED",detail:"登录已失效，请重新登录"}});
    if(path.endsWith("/identity"))return route.fulfill({json:{userId,csrfToken:"test-session-bound-csrf"}});
    if(path.endsWith("/platform-entry"))return route.fulfill({json:{platformUrl:"http://127.0.0.1:3107",demoEnabled:false}});
    if(path.endsWith("/start"))return route.fulfill({json:{...view(),phase:"idle",lessonId:null,messages:[]}});
    if(path.endsWith("/resume")||path===`/api/session/session-${userId}`)return route.fulfill({json:view()});
    writes.push(route.request().postDataJSON());
    throw new Error(`Unexpected write ${path}`);
  });
  await page.goto("/app/?course_id=c");
  await page.getByRole("button",{name:/会话测试课时/}).click();
  await page.getByRole("textbox").fill("只属于原账号的未提交草稿");
  expired=true;
  await page.evaluate(()=>window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("link",{name:"前往平台登录"})).toBeVisible();
  expect(await page.evaluate(()=>localStorage.getItem("student_draft:u:session-u"))).toBe("只属于原账号的未提交草稿");
  expired=false;userId="other";
  await page.reload();
  await page.getByRole("button",{name:/会话测试课时/}).click();
  await expect(page.getByRole("textbox")).toHaveValue("");
  expect(writes).toHaveLength(0);
  userId="u";
  await page.reload();
  await expect(page.getByRole("textbox")).toHaveValue("只属于原账号的未提交草稿");
});
