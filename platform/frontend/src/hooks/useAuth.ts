import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type Body_login_login_access_token as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return localStorage.getItem("platform_session_known") !== null
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: async () => (await UsersService.readUserMe()).data,
    enabled: isLoggedIn(),
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ body: data }),
    onSuccess: () => {
      showSuccessToast("注册成功，请登录")
      navigate({ to: "/login" })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    await LoginService.loginAccessToken({
      body: data,
    })
    localStorage.removeItem("access_token")
    localStorage.setItem("platform_session_known", "1")
    const currentUser = (await UsersService.readUserMe()).data
    queryClient.setQueryData(["currentUser"], currentUser)
    return currentUser
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (currentUser) => {
      const teacher = currentUser.role === "teacher" || currentUser.is_superuser
      const student = currentUser.role === "student"
      navigate({ to: teacher ? "/teacher" : student ? "/student" : "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const logout = async () => {
    await fetch("/api/v1/logout", { method: "POST", credentials: "include" })
    localStorage.removeItem("access_token")
    localStorage.removeItem("platform_session_known")
    queryClient.clear()
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
