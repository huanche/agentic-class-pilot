import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = (description: string) => {
    toast.success("Success!", {
      description,
    })
  }

  const showErrorToast = (description: string) => {
    toast.error(description || "操作失败")
  }

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
