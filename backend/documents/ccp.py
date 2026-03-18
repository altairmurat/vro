import pandas as pd

file_path = "./documents/ccp_vor/CCP.xlsx"


#--------------------------------------------
#we should receive all CCP names
#they are located at from n=2, at n.n, н.n
def punkts_markas_list():
    
    file_path = "./documents/ccp_vor/CCP.xlsx"
    
    read_file = pd.read_excel(file_path, header=None)
    
    punkts_list = [] #list of all punkts
    marka_list = [] #list of all marka elementas

    punkts_column = []
    for i in range(3,len(read_file[0])):
        punkts_column.append(read_file[0][i])
        
    markas_column = []
    for i in range(3,len(read_file[1])):
        markas_column.append(read_file[1][i])
        
    for punkt in punkts_column:
        if len(str(punkt).split(".")) == 2: #все пункты, которые два элемента в листе (2.2 - [2, 2]) не равно 3
            index_punkt = punkts_column.index(punkt)
            punkts_list.append(punkts_column[index_punkt])
            marka_list.append(markas_column[index_punkt])
            
    punkts_markas_list = []
    for i in range(len(punkts_list)):
        punkts_markas_list.append(punkts_list[i] + " " + marka_list[i])
    
    return marka_list
        
#-------------------------------------------
# марка элемента: "стена / не стена" | толщина: ххх-ххх или ххх между 200 и 500 (200-220, 250-500) / бетон: В10 или еще чтото / пункт
def receive_punkts_and_elements_ccp():
    
    file_path = "./documents/ccp_vor/CCP.xlsx"
    
    marka_list = punkts_markas_list()
    
    list_of_dict = []
    marka_dict = {
        "marka": "",
        "class": "",
        "thickness": ""
    }

    for marka in marka_list:
        marka_elementa = marka
        marka_desc_list = str(marka).split(" ")
        marka_dict["marka"] = marka_elementa
        #for desc in marka_desc_list:
        for i in range(len(marka_desc_list)):
            #if marka_desc_list[i][:1] == "B":
            #    marka_dict["class"] = marka_desc_list[i]
            if marka_desc_list[i][:1] == "В":
                marka_dict["class"] = marka_desc_list[i]
            elif marka_desc_list[i][:1] == "F":
                marka_dict["class"] += " " + marka_desc_list[i]
            elif marka_desc_list[i][:1] == "W":
                marka_dict["class"] += " " + marka_desc_list[i]
            elif marka_desc_list[i][:1] == "2":
                marka_dict["thickness"] = marka_desc_list[i]
            elif marka_desc_list[i][:1] == "3":
                marka_dict["thickness"] = marka_desc_list[i]
            elif marka_desc_list[i][:1] == "4":
                marka_dict["thickness"] = marka_desc_list[i]
            elif marka_desc_list[i][:1] == "5":
                marka_dict["thickness"] = marka_desc_list[i]
            else:
                continue
        list_of_dict.append(marka_dict)
        marka_dict = {
            "marka": "",
            "class": "",
            "thickness": ""
        }
    return list_of_dict

def list_of_thicknesses():
    list_of_dicts = receive_punkts_and_elements_ccp()
    list_of_thicks = []
    for i in range(len(list_of_dicts)):
        list_of_thicks.append(list_of_dicts[i]["thickness"])
        
    return list_of_thicks
    
print(receive_punkts_and_elements_ccp())
#print(marka_list)

#group 1

#group 2

#group 3

#group 4